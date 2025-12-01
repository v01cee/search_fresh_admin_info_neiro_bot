from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
import logging

from src.bot.config import get_config
from src.bot.database.buttons import get_all_buttons, get_button_by_callback_data, get_button_by_id
from src.bot.database.start_message import get_start_message
from src.bot.database.button_steps import get_button_steps
from src.bot.handlers.start import FeedbackStates
import asyncio
from src.bot.services.menu_constructor import build_user_inline_keyboard, build_admin_inline_keyboard_with_user_buttons

logger = logging.getLogger(__name__)

callback_router = Router(name="callbacks")

# Маппинг: некоторые кнопки используют дочерние кнопки другой кнопки.
# Пример: кнопка "Функционал РОО" (ID: 76) должна показывать те же дочерние
# кнопки, что и "Функционал РОП" (ID: 34).
ALIAS_CHILDREN_SOURCE = {
    76: 34,
}

# Максимальная длина callback_data в Telegram (64 байта)
MAX_CALLBACK_DATA_LENGTH = 64


def _truncate_callback_data(callback_data: str) -> str:
    """Обрезает callback_data до максимальной длины, если необходимо."""
    if not callback_data:
        return "btn_invalid"
    
    # Если callback_data уже в формате btn_id_XXX, он всегда короткий, не обрезаем
    if callback_data.startswith("btn_id_"):
        return callback_data
    
    # Проверяем длину в байтах
    encoded = callback_data.encode('utf-8')
    if len(encoded) <= MAX_CALLBACK_DATA_LENGTH:
        return callback_data
    
    # Обрезаем по байтам, оставляя место для безопасности
    truncated = encoded[:MAX_CALLBACK_DATA_LENGTH - 1]
    
    # Убеждаемся, что не обрезали в середине UTF-8 символа
    while truncated and truncated[-1] & 0b11000000 == 0b10000000:
        truncated = truncated[:-1]
        if not truncated:
            break
    
    result = truncated.decode('utf-8', errors='ignore')
    
    # Если после обрезки получилась пустая строка, возвращаем минимальный валидный callback_data
    if not result or len(result.encode('utf-8')) == 0:
        # Используем хеш для создания короткого уникального идентификатора
        import hashlib
        hash_suffix = hashlib.md5(callback_data.encode('utf-8')).hexdigest()[:16]
        return f"btn_{hash_suffix}"
    
    return result


def _validate_keyboard(keyboard: InlineKeyboardMarkup) -> tuple[bool, list[str]]:
    """Проверяет, что все callback_data в клавиатуре валидны. Возвращает (валидна ли клавиатура, список проблемных callback_data)."""
    import logging
    logger = logging.getLogger(__name__)
    
    problems = []
    for row in keyboard.inline_keyboard:
        for button in row:
            if button.callback_data:
                byte_length = len(button.callback_data.encode('utf-8'))
                if byte_length > MAX_CALLBACK_DATA_LENGTH:
                    problem_msg = f"длина={byte_length} байт, данные={button.callback_data[:50]}..."
                    logger.error(f"Найден невалидный callback_data в клавиатуре: {problem_msg}")
                    problems.append(problem_msg)
                    # Автоматически обрезаем проблемный callback_data
                    button.callback_data = _truncate_callback_data(button.callback_data)
                    # Проверяем еще раз после обрезки
                    new_byte_length = len(button.callback_data.encode('utf-8'))
                    if new_byte_length > MAX_CALLBACK_DATA_LENGTH:
                        # Если все еще слишком длинный, заменяем на безопасный вариант
                        import hashlib
                        hash_suffix = hashlib.md5(button.callback_data.encode('utf-8')).hexdigest()[:16]
                        button.callback_data = f"btn_{hash_suffix}"
                        logger.warning(f"Заменен проблемный callback_data на: {button.callback_data}")
    
    return len(problems) == 0, problems


def _is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


async def _edit_or_send_message(callback: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup = None) -> None:
    """Редактирует сообщение или отправляет новое, если редактирование невозможно."""
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        # Если сообщение нельзя отредактировать (например, изменился тип контента), отправляем новое
        if "message is not modified" in str(e).lower() or "message can't be edited" in str(e).lower():
            # Сообщение не изменилось или нельзя редактировать - отправляем новое
            await callback.message.answer(text, reply_markup=reply_markup)
        else:
            # Другая ошибка - пробуем отправить новое сообщение
            logger.warning(f"Не удалось отредактировать сообщение: {e}, отправляем новое")
            await callback.message.answer(text, reply_markup=reply_markup)
    except Exception as e:
        # Любая другая ошибка - отправляем новое сообщение
        logger.error(f"Ошибка при редактировании сообщения: {e}, отправляем новое")
        await callback.message.answer(text, reply_markup=reply_markup)


@callback_router.callback_query(F.data.startswith("btn_"))
async def handle_button_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик нажатий на инлайн-кнопки."""
    callback_data = callback.data

    # Получаем информацию о кнопке из БД
    button = await get_button_by_callback_data(callback_data)
    
    # Если кнопка не найдена, но callback_data в формате btn_id_XXX, извлекаем ID
    if not button and callback_data.startswith("btn_id_"):
        try:
            button_id = int(callback_data.replace("btn_id_", ""))
            button = await get_button_by_id(button_id)
        except (ValueError, AttributeError):
            pass

    if button:
        await callback.answer(f"Вы нажали: {button['text']}")
        
        # Получаем дочерние кнопки.
        # Для некоторых кнопок (например, Функционал РОО) берём детей от другой кнопки.
        parent_for_children_id = ALIAS_CHILDREN_SOURCE.get(button["id"], button["id"])
        child_buttons = await get_all_buttons(parent_id=parent_for_children_id)
        
        # Создаём клавиатуру с кнопками
        inline_keyboard = []
        
        # Добавляем дочерние кнопки, если они есть (каждая в отдельный ряд - столбик)
        if child_buttons:
            for btn in child_buttons:
                # Формируем текст кнопки с галочкой и задержкой, если есть
                button_text = btn["text"]
                delay = btn.get("delay", 0)
                if delay and delay > 0:
                    button_text = f"{button_text} ✓ ({delay} сек)"
                
                inline_keyboard.append([
                    InlineKeyboardButton(
                        text=button_text,
                        callback_data=_truncate_callback_data(btn["callback_data"])
                    )
                ])
        
        # Проверяем режим пользователя (user_mode/admin_mode)
        data = await state.get_data()
        admin_mode = data.get("admin_mode", False)
        
        # Показываем админские кнопки только если админ И в режиме админа
        if _is_admin(callback.from_user.id) and admin_mode:
            inline_keyboard.append([
                InlineKeyboardButton(
                    text="➕ Добавить кнопку",
                    callback_data=f"admin_add_button_{button['id']}"
                )
            ])
            inline_keyboard.append([
                InlineKeyboardButton(
                    text="✏️ Изменить текст кнопки",
                    callback_data=f"edit_button_name_{button['id']}"
                )
            ])
            inline_keyboard.append([
                InlineKeyboardButton(
                    text="✏️ Изменить текст",
                    callback_data=f"edit_button_message_{button['id']}"
            )
            ])
            # Кнопка для добавления/удаления файла
            if button.get("file_id"):
                inline_keyboard.append([
                    InlineKeyboardButton(
                        text="📎 Удалить файл",
                        callback_data=f"remove_file_{button['id']}"
                    )
                ])
            else:
                inline_keyboard.append([
                    InlineKeyboardButton(
                        text="📎 Добавить файл",
                        callback_data=f"add_file_{button['id']}"
                    )
                ])
            inline_keyboard.append([
                InlineKeyboardButton(
                    text="🗑️ Удалить кнопку",
                    callback_data=f"delete_button_{button['id']}"
                )
            ])
        
        # Кнопка "Назад"
        if button.get("parent_id"):
            # Если есть родитель, возвращаемся к нему
            parent_button = await get_button_by_id(button["parent_id"])
            if parent_button:
                inline_keyboard.append([
                    InlineKeyboardButton(
                        text="◀️ Назад",
                        callback_data=_truncate_callback_data(parent_button["callback_data"])
                    )
                ])
        else:
            # Если нет родителя, возвращаемся в главное меню
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
            ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        
        # Получаем шаги кнопки
        steps = await get_button_steps(button['id'])
        
        # Проверяем, является ли пользователь админом
        is_admin_user = _is_admin(callback.from_user.id)
        
        # Проверяем режим пользователя
        data = await state.get_data()
        admin_mode = data.get("admin_mode", False)
        user_mode = data.get("user_mode", False)
        
        # Показываем админское меню только если админ И в режиме админа (не в режиме пользователя)
        if is_admin_user and admin_mode and not user_mode:
            # Если есть шаги и пользователь админ - НЕ отправляем шаги, показываем только админскую клавиатуру
            admin_keyboard = []
            
            # Сначала добавляем дочерние кнопки, если они есть
            if child_buttons:
                for btn in child_buttons:
                    button_text = btn["text"]
                    delay = btn.get("delay", 0)
                    if delay and delay > 0:
                        button_text = f"{button_text} ✓ ({delay} сек)"
                    admin_keyboard.append([
                        InlineKeyboardButton(text=button_text, callback_data=_truncate_callback_data(btn["callback_data"]))
                    ])
            
            # Кнопка "Редактировать шаги"
            admin_keyboard.append([
                InlineKeyboardButton(text="✏️ Редактировать шаги", callback_data=f"edit_steps_{button['id']}")
            ])
            
            # Админские кнопки
            admin_keyboard.append([
                InlineKeyboardButton(text="➕ Добавить кнопку", callback_data=f"admin_add_button_{button['id']}")
            ])
            admin_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст кнопки", callback_data=f"edit_button_name_{button['id']}")
            ])
            admin_keyboard.append([
                InlineKeyboardButton(text="↕️ Сместить кнопку", callback_data=f"move_button_{button['id']}")
            ])
            admin_keyboard.append([
                InlineKeyboardButton(text="🗑️ Удалить кнопку", callback_data=f"delete_button_{button['id']}")
            ])
            
            # Кнопка "Назад"
            if button.get("parent_id"):
                parent_button = await get_button_by_id(button["parent_id"])
                if parent_button:
                    admin_keyboard.append([
                        InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(parent_button["callback_data"]))
                    ])
            else:
                admin_keyboard.append([
                    InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
                ])
            
            admin_kb = InlineKeyboardMarkup(inline_keyboard=admin_keyboard)
            
            # Валидируем и исправляем клавиатуру перед отправкой
            is_valid, problems = _validate_keyboard(admin_kb)
            if problems:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Обнаружены проблемные callback_data, исправлены: {problems}")
            
            # Редактируем сообщение вместо отправки нового
            await _edit_or_send_message(
                callback,
                f"Кнопка: <b>{button['text']}</b> (ID: {button['id']})\n"
                f"Количество шагов: {len(steps)}",
                reply_markup=admin_kb
            )
        elif steps:
            # Строим клавиатуру заранее, чтобы прикрепить к последнему шагу
            final_keyboard = None
            # Проверяем режим пользователя
            data = await state.get_data()
            admin_mode = data.get("admin_mode", False)
            user_mode = data.get("user_mode", False)
            
            # Показываем админское меню только если админ И в режиме админа (не в режиме пользователя)
            if is_admin_user and admin_mode and not user_mode:
                admin_keyboard = []
                
                # Сначала добавляем дочерние кнопки, если они есть
                if child_buttons:
                    for btn in child_buttons:
                        button_text = btn["text"]
                        delay = btn.get("delay", 0)
                        if delay and delay > 0:
                            button_text = f"{button_text} ✓ ({delay} сек)"
                        admin_keyboard.append([
                            InlineKeyboardButton(text=button_text, callback_data=_truncate_callback_data(btn["callback_data"]))
                        ])
                
                # Кнопка "Редактировать шаги"
                admin_keyboard.append([
                    InlineKeyboardButton(text="✏️ Редактировать шаги", callback_data=f"edit_steps_{button['id']}")
                ])
                
                # Админские кнопки
                admin_keyboard.append([
                    InlineKeyboardButton(text="➕ Добавить кнопку", callback_data=f"admin_add_button_{button['id']}")
                ])
                admin_keyboard.append([
                    InlineKeyboardButton(text="✏️ Изменить текст кнопки", callback_data=f"edit_button_name_{button['id']}")
                ])
                admin_keyboard.append([
                    InlineKeyboardButton(text="↕️ Сместить кнопку", callback_data=f"move_button_{button['id']}")
                ])
                admin_keyboard.append([
                    InlineKeyboardButton(text="🗑️ Удалить кнопку", callback_data=f"delete_button_{button['id']}")
                ])
                
                # Кнопка "Назад"
                if button.get("parent_id"):
                    parent_button = await get_button_by_id(button["parent_id"])
                    if parent_button:
                        admin_keyboard.append([
                            InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(parent_button["callback_data"]))
                        ])
                else:
                    admin_keyboard.append([
                        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
                    ])
                
                final_keyboard = InlineKeyboardMarkup(inline_keyboard=admin_keyboard)
            else:
                # Для обычных пользователей строим клавиатуру с дочерними кнопками и кнопкой "Назад"
                user_keyboard = []
                
                # Добавляем дочерние кнопки, если они есть
                if child_buttons:
                    for btn in child_buttons:
                        button_text = btn["text"]
                        delay = btn.get("delay", 0)
                        if delay and delay > 0:
                            button_text = f"{button_text} ✓ ({delay} сек)"
                        user_keyboard.append([
                            InlineKeyboardButton(
                                text=button_text,
                                callback_data=_truncate_callback_data(btn["callback_data"])
                            )
                        ])
                
                # Кнопка "Назад"
                if button.get("parent_id"):
                    parent_button = await get_button_by_id(button["parent_id"])
                    if parent_button:
                        user_keyboard.append([
                            InlineKeyboardButton(
                                text="◀️ Назад",
                                callback_data=_truncate_callback_data(parent_button["callback_data"])
                            )
                        ])
                else:
                    user_keyboard.append([
                        InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
                    ])
                
                final_keyboard = InlineKeyboardMarkup(inline_keyboard=user_keyboard) if user_keyboard else None
            
            # Если есть шаги и пользователь не админ (или админ не в админском режиме) - отправляем все шаги
            # Используем bot напрямую для гарантированной отправки новых сообщений
            # НЕ редактируем существующие сообщения, только отправляем новые
            bot = callback.bot
            chat_id = callback.message.chat.id
            
            for i, step in enumerate(steps):
                # Если это не первый шаг и есть задержка - ждем
                if i > 0 and step.get("delay", 0) > 0:
                    await asyncio.sleep(step["delay"])
                
                content_type = step.get("content_type")
                content_text = step.get("content_text", "")
                file_id = step.get("file_id")
                file_type = step.get("file_type")
                
                # Определяем, это последний шаг?
                is_last_step = (i == len(steps) - 1)
                
                if content_type == "text":
                    # Отправляем текст новым сообщением
                    if content_text:
                        # Если это последний шаг, прикрепляем клавиатуру
                        if is_last_step and final_keyboard:
                            await bot.send_message(chat_id=chat_id, text=content_text, reply_markup=final_keyboard)
                        else:
                            await bot.send_message(chat_id=chat_id, text=content_text)
                elif content_type == "file" and file_id:
                    # Telegram ограничивает caption до 1024 символов
                    MAX_CAPTION_LENGTH = 1024
                    caption = None
                    text_to_send_separately = None
                    
                    if content_text:
                        if len(content_text) <= MAX_CAPTION_LENGTH:
                            caption = content_text
                        else:
                            # Если текст длиннее, отправляем его отдельным сообщением
                            text_to_send_separately = content_text
                    
                    # Отправляем файл в зависимости от типа
                    # Если это последний шаг, прикрепляем клавиатуру
                    reply_markup = final_keyboard if is_last_step else None
                    
                    try:
                        if file_type == "photo":
                            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, reply_markup=reply_markup)
                        elif file_type == "video":
                            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption, reply_markup=reply_markup)
                        elif file_type == "document":
                            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption, reply_markup=reply_markup)
                        elif file_type == "audio":
                            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption, reply_markup=reply_markup)
                        elif file_type == "voice":
                            await bot.send_voice(chat_id=chat_id, voice=file_id, caption=caption, reply_markup=reply_markup)
                        elif file_type == "video_note":
                            await bot.send_video_note(chat_id=chat_id, video_note=file_id, reply_markup=reply_markup)
                        else:
                            # По умолчанию отправляем как документ
                            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption, reply_markup=reply_markup)
                        
                        # Если текст был слишком длинным и должен был отправиться отдельно
                        if text_to_send_separately:
                            if is_last_step and final_keyboard:
                                await bot.send_message(chat_id=chat_id, text=text_to_send_separately, reply_markup=final_keyboard)
                            else:
                                await bot.send_message(chat_id=chat_id, text=text_to_send_separately)
                    except TelegramBadRequest as e:
                        logger.error(f"Ошибка при отправке файла (шаг {i+1}): {e}. file_id={file_id}, file_type={file_type}")
                        # Отправляем сообщение об ошибке
                        error_msg = f"⚠️ Не удалось отправить файл (файл больше не доступен)."
                        if caption:
                            error_msg += f"\n\n{caption}"
                        elif content_text:
                            error_msg += f"\n\n{content_text}"
                        
                        if is_last_step and final_keyboard:
                            await bot.send_message(chat_id=chat_id, text=error_msg, reply_markup=final_keyboard)
                        else:
                            await bot.send_message(chat_id=chat_id, text=error_msg)
                        
                        # Если текст был слишком длинным и должен был отправиться отдельно
                        if text_to_send_separately:
                            if is_last_step and final_keyboard:
                                await bot.send_message(chat_id=chat_id, text=text_to_send_separately, reply_markup=final_keyboard)
                            else:
                                await bot.send_message(chat_id=chat_id, text=text_to_send_separately)
                    
            
            # Клавиатура уже прикреплена к последнему шагу, больше ничего не отправляем
        else:
            # Если шагов нет, используем старую логику (для обратной совместимости)
            file_id = button.get("file_id")
            file_type = button.get("file_type")
            message_text = button.get("message_text", "")
            
            if file_id:
                # Отправляем файл в зависимости от типа
                try:
                    if file_type == "photo":
                        await callback.message.answer_photo(photo=file_id, caption=message_text, reply_markup=kb)
                    elif file_type == "video":
                        await callback.message.answer_video(video=file_id, caption=message_text, reply_markup=kb)
                    elif file_type == "document":
                        await callback.message.answer_document(document=file_id, caption=message_text, reply_markup=kb)
                    elif file_type == "audio":
                        await callback.message.answer_audio(audio=file_id, caption=message_text, reply_markup=kb)
                    elif file_type == "voice":
                        await callback.message.answer_voice(voice=file_id, caption=message_text, reply_markup=kb)
                    elif file_type == "video_note":
                        await callback.message.answer_video_note(video_note=file_id, reply_markup=kb)
                    else:
                        # По умолчанию отправляем как документ
                        await callback.message.answer_document(document=file_id, caption=message_text, reply_markup=kb)
                except TelegramBadRequest as e:
                    logger.error(f"Ошибка при отправке файла (старая логика): {e}. file_id={file_id}, file_type={file_type}")
                    # Отправляем сообщение об ошибке
                    error_msg = f"⚠️ Не удалось отправить файл (файл больше не доступен)."
                    if message_text:
                        error_msg += f"\n\n{message_text}"
                    await callback.message.answer(error_msg, reply_markup=kb)
            else:
                # Показываем сохранённый текст сообщения или стартовое сообщение из БД
                if not message_text:
                    # Если текст сообщения не задан, показываем стартовое сообщение из БД
                    message_text = await get_start_message()
                # Редактируем сообщение вместо отправки нового
                await _edit_or_send_message(callback, message_text, reply_markup=kb)
    else:
        await callback.answer("Кнопка не найдена", show_alert=True)


@callback_router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню."""
    start_message = await get_start_message()
    
    # Проверяем режим пользователя
    data = await state.get_data()
    admin_mode = data.get("admin_mode", False)
    
    # Если админ в режиме админа - показываем админские кнопки
    if _is_admin(callback.from_user.id) and admin_mode:
        kb = await build_admin_inline_keyboard_with_user_buttons()
    else:
        # Для всех остальных - только пользовательские кнопки
        kb = await build_user_inline_keyboard()
    
    await callback.answer()
    # Редактируем сообщение вместо отправки нового
    await _edit_or_send_message(callback, start_message, reply_markup=kb)


@callback_router.callback_query(F.data == "feedback")
async def handle_feedback_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик кнопки 'Обратная связь'."""
    user_id = callback.from_user.id
    username = callback.from_user.username or "не указан"
    logger.info(f"[CALLBACK] Пользователь {user_id} (@{username}) нажал кнопку: feedback")
    
    feedback_text = "Здесь вы можете оставить свою обратную связь/вопросы предложения"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать нам", callback_data="write_to_us_from_feedback")],
            [InlineKeyboardButton(text="<- Назад", callback_data="back_to_menu")]
        ]
    )
    
    await callback.answer()
    await _edit_or_send_message(callback, feedback_text, reply_markup=keyboard)


@callback_router.callback_query(F.data == "write_to_us_from_feedback")
async def handle_write_to_us_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик кнопки 'Написать нам' из меню обратной связи."""
    user_id = callback.from_user.id
    username = callback.from_user.username or "не указан"
    logger.info(f"[CALLBACK] Пользователь {user_id} (@{username}) нажал кнопку: write_to_us_from_feedback")
    
    prompt_text = "Напишите нам ваше сообщение:"
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="<- Назад", callback_data="feedback")]
        ]
    )
    
    # Устанавливаем состояние ожидания сообщения
    await state.set_state(FeedbackStates.waiting_for_feedback_message)
    
    await callback.answer()
    await _edit_or_send_message(callback, prompt_text, reply_markup=keyboard)

