from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from src.bot.config import get_config
from src.bot.database.buttons import get_all_buttons, get_button_by_callback_data, get_button_by_id
from src.bot.database.start_message import get_start_message
from src.bot.database.button_steps import get_button_steps
import asyncio
from src.bot.services.menu_constructor import build_user_inline_keyboard, build_admin_inline_keyboard_with_user_buttons

callback_router = Router(name="callbacks")

# Максимальная длина callback_data в Telegram (64 байта)
MAX_CALLBACK_DATA_LENGTH = 64


def _truncate_callback_data(callback_data: str) -> str:
    """Обрезает callback_data до максимальной длины, если необходимо."""
    if not callback_data:
        return "btn_invalid"
    
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


def _is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


@callback_router.callback_query(F.data.startswith("btn_"))
async def handle_button_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик нажатий на инлайн-кнопки."""
    callback_data = callback.data

    # Получаем информацию о кнопке из БД
    button = await get_button_by_callback_data(callback_data)

    if button:
        await callback.answer(f"Вы нажали: {button['text']}")
        
        # Получаем дочерние кнопки
        child_buttons = await get_all_buttons(parent_id=button['id'])
        
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
                        callback_data=parent_button["callback_data"]
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
        
        # Проверяем режим админа и устанавливаем, если админ
        data = await state.get_data()
        admin_mode = data.get("admin_mode", False)
        
        # Если пользователь админ, но admin_mode не установлен - устанавливаем его
        if is_admin_user and not admin_mode:
            await state.update_data(admin_mode=True, user_mode=False)
            admin_mode = True
        
        # Если пользователь админ - ВСЕГДА показываем админ-меню, независимо от admin_mode в state
        if is_admin_user:
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
                        InlineKeyboardButton(text=button_text, callback_data=btn["callback_data"])
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
            await callback.message.answer(
                f"Кнопка: <b>{button['text']}</b>\n"
                f"Количество шагов: {len(steps)}",
                reply_markup=admin_kb
            )
        elif steps:
            # Если есть шаги и пользователь не админ (или админ не в админском режиме) - отправляем все шаги
            for i, step in enumerate(steps):
                # Если это не первый шаг и есть задержка - ждем
                if i > 0 and step.get("delay", 0) > 0:
                    await asyncio.sleep(step["delay"])
                
                content_type = step.get("content_type")
                content_text = step.get("content_text", "")
                file_id = step.get("file_id")
                file_type = step.get("file_type")
                
                if content_type == "text":
                    # Отправляем текст
                    if content_text:
                        await callback.message.answer(content_text)
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
                    if file_type == "photo":
                        await callback.message.answer_photo(photo=file_id, caption=caption)
                    elif file_type == "video":
                        await callback.message.answer_video(video=file_id, caption=caption)
                    elif file_type == "document":
                        await callback.message.answer_document(document=file_id, caption=caption)
                    elif file_type == "audio":
                        await callback.message.answer_audio(audio=file_id, caption=caption)
                    elif file_type == "voice":
                        await callback.message.answer_voice(voice=file_id, caption=caption)
                    elif file_type == "video_note":
                        await callback.message.answer_video_note(video_note=file_id)
                    else:
                        # По умолчанию отправляем как документ
                        await callback.message.answer_document(document=file_id, caption=caption)
                    
                    # Если текст был слишком длинным, отправляем его отдельным сообщением
                    if text_to_send_separately:
                        await callback.message.answer(text_to_send_separately)
            
            # После отправки всех шагов показываем клавиатуру
            # Если пользователь админ - ВСЕГДА показываем админскую клавиатуру
            # (admin_mode уже проверен и установлен выше, но проверяем is_admin_user для надежности)
            if is_admin_user:
                admin_keyboard = []
                
                # Сначала добавляем дочерние кнопки, если они есть
                if child_buttons:
                    for btn in child_buttons:
                        button_text = btn["text"]
                        delay = btn.get("delay", 0)
                        if delay and delay > 0:
                            button_text = f"{button_text} ✓ ({delay} сек)"
                        admin_keyboard.append([
                            InlineKeyboardButton(text=button_text, callback_data=btn["callback_data"])
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
                await callback.message.answer("◀️ Назад в меню", reply_markup=admin_kb)
            else:
                await callback.message.answer("◀️ Назад в меню", reply_markup=kb)
        else:
            # Если шагов нет, используем старую логику (для обратной совместимости)
            file_id = button.get("file_id")
            file_type = button.get("file_type")
            message_text = button.get("message_text", "")
            
            if file_id:
                # Отправляем файл в зависимости от типа
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
            else:
                # Показываем сохранённый текст сообщения или стартовое сообщение из БД
                if not message_text:
                    # Если текст сообщения не задан, показываем стартовое сообщение из БД
                    message_text = await get_start_message()
                await callback.message.answer(message_text, reply_markup=kb)
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
    await callback.message.answer(start_message, reply_markup=kb)

