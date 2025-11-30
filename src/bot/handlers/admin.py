from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
import logging

from src.bot.config import get_config
from src.bot.keyboards.common import admin_inline_keyboard
from src.bot.database.buttons import (
    add_button_to_db, get_all_buttons, update_button_text,
    update_button_message_text, delete_button, get_button_by_id,
    update_button_file, remove_button_file, get_button_by_callback_data
)
from src.bot.database.button_steps import (
    add_button_step, get_button_steps, delete_button_steps,
    get_button_step, delete_button_step, update_step_delay, update_step_content,
    insert_step_at_position
)
from src.bot.services.menu_constructor import build_admin_inline_keyboard_with_user_buttons
from src.bot.database.start_message import get_start_message


admin_router = Router(name="admin")


class AdminStates(StatesGroup):
    # Состояния для создания новой кнопки
    waiting_for_new_button_text = State()  # Ожидание названия кнопки
    waiting_for_new_button_content = State()  # Ожидание контента (текст/файл)
    waiting_for_file_caption = State()  # Ожидание текста для файла (опционально)
    waiting_for_button_finalization = State()  # Финальный шаг (задержка или завершение)
    waiting_for_delay = State()  # Ожидание задержки в секундах
    
    # Состояния для редактирования
    waiting_for_button_selection_to_edit = State()
    waiting_for_new_text_for_button = State()
    waiting_for_new_button_name = State()
    waiting_for_new_message_text = State()
    waiting_for_new_start_message = State()
    waiting_for_file = State()  # Ожидание загрузки файла для существующей кнопки
    waiting_for_file_caption_for_button = State()  # Ожидание текста для файла существующей кнопки
    waiting_for_step_delay = State()  # Ожидание задержки для шага
    waiting_for_step_text = State()  # Ожидание нового текста для шага
    waiting_for_step_file_caption = State()  # Ожидание текста для файла при изменении шага
    waiting_for_new_step_content = State()  # Ожидание контента для нового шага
    waiting_for_new_step_file_caption = State()  # Ожидание текста для файла нового шага
    waiting_for_new_step_position = State()  # Ожидание позиции для нового шага


def _is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


# Максимальная длина callback_data в Telegram (64 байта)
MAX_CALLBACK_DATA_LENGTH = 64


def _truncate_callback_data(callback_data: str) -> str:
    """Обрезает callback_data до максимальной длины, если необходимо."""
    if not callback_data:
        return "btn_invalid"
    
    # Если callback_data уже в формате btn_id_XXX, он всегда короткий, не обрезаем
    if callback_data.startswith("btn_id_"):
        return callback_data
    
    encoded = callback_data.encode('utf-8')
    if len(encoded) <= MAX_CALLBACK_DATA_LENGTH:
        return callback_data
    
    truncated = encoded[:MAX_CALLBACK_DATA_LENGTH - 1]
    while truncated and truncated[-1] & 0b11000000 == 0b10000000:
        truncated = truncated[:-1]
        if not truncated:
            break
    
    result = truncated.decode('utf-8', errors='ignore')
    if not result or len(result.encode('utf-8')) == 0:
        import hashlib
        hash_suffix = hashlib.md5(callback_data.encode('utf-8')).hexdigest()[:16]
        return f"btn_{hash_suffix}"
    
    return result


async def _preserve_admin_mode(state: FSMContext, user_id: int) -> None:
    """Сохраняет режим админа при очистке состояния."""
    if _is_admin(user_id):
        await state.update_data(admin_mode=True, user_mode=False)


async def _clear_state_preserving_admin(state: FSMContext, user_id: int) -> None:
    """Очищает состояние, сохраняя админский режим."""
    # Сохраняем админский режим перед очисткой
    is_admin = _is_admin(user_id)
    admin_mode_before = False
    if is_admin:
        data_before = await state.get_data()
        admin_mode_before = data_before.get("admin_mode", False)
    
    # Очищаем состояние
    await state.clear()
    
    # Восстанавливаем админский режим сразу после очистки
    if is_admin:
        # Всегда устанавливаем админский режим для админа, даже если он не был установлен
        await state.update_data(admin_mode=True, user_mode=False)
        
        # Проверяем, что админский режим установлен
        data_after = await state.get_data()
        if not data_after.get("admin_mode", False):
            # Если не установился, пробуем еще раз
            await state.update_data(admin_mode=True, user_mode=False)


async def _build_button_view_keyboard(button_id: int, state: FSMContext, user_id: int) -> tuple[InlineKeyboardMarkup, str]:
    """Строит клавиатуру для просмотра кнопки админом. Возвращает (клавиатура, текст сообщения)."""
    button = await get_button_by_id(button_id)
    if not button:
        admin_kb = await build_admin_inline_keyboard_with_user_buttons()
        return admin_kb, "❌ Кнопка не найдена."
    
    # Получаем дочерние кнопки
    child_buttons = await get_all_buttons(parent_id=button['id'])
    
    # Получаем шаги кнопки
    steps = await get_button_steps(button['id'])
    
    # Проверяем, является ли пользователь админом
    is_admin_user = _is_admin(user_id)
    
    # Проверяем режим админа и явно устанавливаем, если админ
    data = await state.get_data()
    admin_mode = data.get("admin_mode", False)
    
    # Если пользователь админ, но admin_mode не установлен - устанавливаем его
    if is_admin_user and not admin_mode:
        await state.update_data(admin_mode=True, user_mode=False)
        admin_mode = True
    
    inline_keyboard = []
    
    # Если пользователь админ - ВСЕГДА показываем админскую клавиатуру, независимо от admin_mode в state
    # (admin_mode нужен для других проверок, но для показа меню достаточно проверки _is_admin)
    if is_admin_user:
        # Сначала добавляем дочерние кнопки, если они есть
        if child_buttons:
            for btn in child_buttons:
                button_text = btn["text"]
                delay = btn.get("delay", 0)
                if delay and delay > 0:
                    button_text = f"{button_text} ✓ ({delay} сек)"
                inline_keyboard.append([
                    InlineKeyboardButton(text=button_text, callback_data=_truncate_callback_data(btn["callback_data"]))
                ])
        
        # Кнопка "Редактировать шаги" (показываем всегда, даже если шагов нет)
        inline_keyboard.append([
            InlineKeyboardButton(text="✏️ Редактировать шаги", callback_data=f"edit_steps_{button['id']}")
        ])
        
        # Админские кнопки
        inline_keyboard.append([
            InlineKeyboardButton(text="➕ Добавить кнопку", callback_data=f"admin_add_button_{button['id']}")
        ])
        inline_keyboard.append([
            InlineKeyboardButton(text="✏️ Изменить текст кнопки", callback_data=f"edit_button_name_{button['id']}")
        ])
        inline_keyboard.append([
            InlineKeyboardButton(text="🗑️ Удалить кнопку", callback_data=f"delete_button_{button['id']}")
        ])
        
        # Кнопка "Назад"
        if button.get("parent_id"):
            parent_button = await get_button_by_id(button["parent_id"])
            if parent_button:
                inline_keyboard.append([
                    InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(parent_button["callback_data"]))
                ])
        else:
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
            ])
        
        message_text = f"Кнопка: <b>{button['text']}</b>\nКоличество шагов: {len(steps)}"
    else:
        # Обычная клавиатура с дочерними кнопками
        if child_buttons:
            for btn in child_buttons:
                button_text = btn["text"]
                delay = btn.get("delay", 0)
                if delay and delay > 0:
                    button_text = f"{button_text} ✓ ({delay} сек)"
                inline_keyboard.append([
                    InlineKeyboardButton(text=button_text, callback_data=_truncate_callback_data(btn["callback_data"]))
                ])
        
        # Админские кнопки, если админ в режиме админа
        if _is_admin(user_id) and admin_mode:
            inline_keyboard.append([
                InlineKeyboardButton(text="➕ Добавить кнопку", callback_data=f"admin_add_button_{button['id']}")
            ])
            inline_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст кнопки", callback_data=f"edit_button_name_{button['id']}")
            ])
            inline_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"edit_button_message_{button['id']}")
            ])
            # Кнопка для добавления/удаления файла
            if button.get("file_id"):
                inline_keyboard.append([
                    InlineKeyboardButton(text="📎 Удалить файл", callback_data=f"remove_file_{button['id']}")
                ])
            else:
                inline_keyboard.append([
                    InlineKeyboardButton(text="📎 Добавить файл", callback_data=f"add_file_{button['id']}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="🗑️ Удалить кнопку", callback_data=f"delete_button_{button['id']}")
            ])
        
        # Кнопка "Назад"
        if button.get("parent_id"):
            parent_button = await get_button_by_id(button["parent_id"])
            if parent_button:
                inline_keyboard.append([
                    InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(parent_button["callback_data"]))
                ])
        else:
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
            ])
        
        message_text = f"✅ Название кнопки успешно изменено на: <b>{button['text']}</b>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    return kb, message_text


def _get_delay_button_text(delay: int = 0) -> str:
    """Формирует текст кнопки задержки в зависимости от наличия задержки."""
    if delay and delay > 0:
        return f"⏱️ Изменить задержку({delay})✅"
    return "⏱️ Добавить задержку"


def _get_next_step_delay(data: dict) -> int:
    """Получает задержку для следующего шага из состояния."""
    return data.get("next_delay", 0)


@admin_router.message(Command("admin"))
async def admin_entry(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("У вас нет прав для входа в админ-панель.")
        return

    # Устанавливаем режим админа
    await state.update_data(user_mode=False, admin_mode=True)

    from src.bot.database.start_message import get_start_message
    
    # Показываем то же стартовое сообщение, но с инлайн-кнопками (пользовательские + админские)
    admin_kb = await build_admin_inline_keyboard_with_user_buttons()
    start_text = await get_start_message()
    
    await message.answer(start_text, reply_markup=admin_kb)


@admin_router.callback_query(F.data.startswith("admin_add_button_"))
async def admin_add_button_start_with_parent(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало создания кнопки внутри другой кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    try:
        await _clear_state_preserving_admin(state, callback.from_user.id)
        
        parent_id_str = callback.data.replace("admin_add_button_", "")
        if not parent_id_str:
            await callback.answer("Ошибка: не указан ID родительской кнопки.", show_alert=True)
            return
        
        parent_id = int(parent_id_str)
        await state.update_data(steps=[], next_delay=0, parent_id=parent_id)
        await state.set_state(AdminStates.waiting_for_new_button_text)
        await callback.answer()
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_button_creation")]
        ])
        
        await callback.message.answer("Отправь название кнопки:", reply_markup=cancel_kb)
    except ValueError:
        await callback.answer("Ошибка: некорректный ID родительской кнопки.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data == "admin_add_button")
async def admin_add_button_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало создания кнопки в главном меню."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    await _clear_state_preserving_admin(state, callback.from_user.id)
    await state.update_data(steps=[], next_delay=0, parent_id=None)
    await state.set_state(AdminStates.waiting_for_new_button_text)
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_button_creation")]
    ])
    
    await callback.message.answer("Отправь название кнопки:", reply_markup=cancel_kb)


@admin_router.message(AdminStates.waiting_for_new_button_text, F.text)
async def admin_add_button_text_save(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Название кнопки пустое. Отправь непустое название.")
        return
    
    # Проверяем длину названия кнопки (максимум 35 символов)
    if len(text) > 35:
        await message.answer(f"❌ Название кнопки слишком длинное. Максимум 35 символов. Текущая длина: {len(text)} символов.\n\nОтправь название кнопки снова:")
        return

    # Сохраняем название кнопки в состояние и переходим к следующему шагу
    await state.update_data(button_text=text)
    await state.set_state(AdminStates.waiting_for_new_button_content)
    
    # Кнопка отмены
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_button_creation")]
    ])
    
    await message.answer(
        f"Название кнопки: <b>{text}</b>\n\n"
        "Теперь отправь текст, фото, видео или документ, который будет приходить по нажатию на кнопку:",
        reply_markup=cancel_kb
    )


@admin_router.message(AdminStates.waiting_for_new_button_content, F.text)
async def admin_add_button_content_text(message: Message, state: FSMContext) -> None:
    """Обработка текста как контента кнопки."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    content_text = (message.text or "").strip()
    
    # Получаем текущие шаги из состояния
    data = await state.get_data()
    steps = data.get("steps", [])
    next_delay = data.get("next_delay", 0)  # Задержка для следующего шага
    
    # Добавляем новый шаг с задержкой (если это не первый шаг)
    step_number = len(steps) + 1
    steps.append({
        "step_number": step_number,
        "content_type": "text",
        "content_text": content_text,
        "file_id": None,
        "file_type": None,
        "delay": next_delay if step_number > 1 else 0  # Задержка только для шагов после первого
    })
    
    # Сохраняем шаги в состояние и сбрасываем задержку для следующего шага
    await state.update_data(steps=steps, next_delay=0)
    
    # Показываем сообщение о загрузке шага
    await message.answer(f"✅ {step_number} шаг загружен: Текст")
    
    # Клавиатура для финализации (показываем задержку для следующего шага)
    delay = 0  # Пока нет следующего шага, задержка 0
    finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
        [InlineKeyboardButton(text=_get_delay_button_text(delay), callback_data="button_add_delay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
    ])
    
    await message.answer(
        "Это всё или переходим к следующему шагу?",
        reply_markup=finalization_kb
    )
    
    await state.set_state(AdminStates.waiting_for_button_finalization)


@admin_router.message(AdminStates.waiting_for_new_button_content, F.photo | F.video | F.document | F.audio | F.voice | F.video_note)
async def admin_add_button_content_file(message: Message, state: FSMContext) -> None:
    """Обработка файла как контента кнопки."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    # Определяем тип файла и получаем file_id
    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.video_note:
        file_id = message.video_note.file_id
        file_type = "video_note"

    if not file_id:
        await message.answer("❌ Не удалось получить файл. Попробуй еще раз.")
        return

    # Сохраняем файл во временное состояние (для добавления текста)
    await state.update_data(
        current_file_id=file_id,
        current_file_type=file_type
    )
    
    # Спрашиваем нужен ли текст к файлу
    file_caption_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="file_caption_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="file_caption_skip")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="file_caption_cancel")]
    ])
    
    await message.answer(
        f"✅ Файл получен: {file_type}\n\n"
        "Нужно ли описание к этому файлу?",
        reply_markup=file_caption_kb
    )
    
    await state.set_state(AdminStates.waiting_for_file_caption)


@admin_router.callback_query(F.data == "admin_edit_button")
async def admin_edit_button(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer("Функция изменения кнопки пока в разработке.", reply_markup=admin_inline_keyboard())


@admin_router.callback_query(F.data == "admin_edit_text")
async def admin_edit_text_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Редактирование стартового сообщения из админ-панели."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    from src.bot.database.start_message import get_start_message
    
    current_text = await get_start_message()
    await state.set_state(AdminStates.waiting_for_new_start_message)
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_edit_text_cancel")]
    ])
    
    await callback.message.answer(
        f"Текущее стартовое сообщение:\n\n<b>{current_text}</b>\n\n"
        "Отправь новый текст для стартового сообщения:",
        reply_markup=cancel_kb
    )




@admin_router.message(AdminStates.waiting_for_new_start_message, F.text)
async def admin_edit_start_message_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового стартового сообщения."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Текст пустой. Отправь непустой текст.")
        return

    try:
        from src.bot.database.start_message import update_start_message, get_start_message
        success = await update_start_message(new_text)
        
        if success:
            # Очищаем состояние, сохраняя админский режим
            await _clear_state_preserving_admin(state, message.from_user.id)
            
            # Сначала отправляем сообщение об успехе
            await message.answer("✅ Стартовое сообщение успешно изменено.")
            
            # Затем отправляем клавиатуру с уже изменённым стартовым сообщением
            admin_kb = await build_admin_inline_keyboard_with_user_buttons()
            updated_start_text = await get_start_message()
            await message.answer(updated_start_text, reply_markup=admin_kb)
        else:
            await message.answer("❌ Не удалось обновить стартовое сообщение.")
            await _clear_state_preserving_admin(state, message.from_user.id)
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении стартового сообщения: {e}")
        await _clear_state_preserving_admin(state, message.from_user.id)


@admin_router.callback_query(F.data.startswith("edit_text_btn_"))
async def admin_edit_text_select_button(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    # Извлекаем ID кнопки из callback_data
    button_id = int(callback.data.replace("edit_text_btn_", ""))
    
    # Сохраняем ID в состояние
    await state.update_data(button_id=button_id)
    await state.set_state(AdminStates.waiting_for_new_text_for_button)
    
    buttons = await get_all_buttons()
    button = next((b for b in buttons if b['id'] == button_id), None)
    
    if button:
        await callback.answer()
        await callback.message.answer(
            f"Текущий текст кнопки: <b>{button['text']}</b>\n"
            "Отправь новый текст для этой кнопки:"
        )
    else:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        await _clear_state_preserving_admin(state, callback.from_user.id)


@admin_router.callback_query(F.data.startswith("edit_button_name_cancel_"))
async def edit_button_name_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена изменения названия кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    button_id = int(callback.data.replace("edit_button_name_cancel_", ""))
    await _clear_state_preserving_admin(state, callback.from_user.id)
    
    button_kb, button_text = await _build_button_view_keyboard(button_id, state, callback.from_user.id)
    await callback.answer("Отменено")
    await callback.message.answer(button_text, reply_markup=button_kb)


@admin_router.callback_query(F.data.startswith("edit_button_message_cancel_"))
async def edit_button_message_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена изменения текста сообщения кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    button_id = int(callback.data.replace("edit_button_message_cancel_", ""))
    await _clear_state_preserving_admin(state, callback.from_user.id)
    
    button_kb, button_text = await _build_button_view_keyboard(button_id, state, callback.from_user.id)
    await callback.answer("Отменено")
    await callback.message.answer(button_text, reply_markup=button_kb)


@admin_router.callback_query(F.data.startswith("add_file_cancel_"))
async def add_file_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена добавления файла к кнопке."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    button_id = int(callback.data.replace("add_file_cancel_", ""))
    await _clear_state_preserving_admin(state, callback.from_user.id)
    
    button_kb, button_text = await _build_button_view_keyboard(button_id, state, callback.from_user.id)
    await callback.answer("Отменено")
    await callback.message.answer(button_text, reply_markup=button_kb)


@admin_router.callback_query(F.data == "button_delay_cancel")
async def button_delay_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена добавления задержки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_button_finalization)
    await callback.answer("Отменено")
    
    data = await state.get_data()
    delay = data.get("next_delay", 0)
    
    finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
        [InlineKeyboardButton(text=_get_delay_button_text(delay), callback_data="button_add_delay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
    ])
    
    await callback.message.answer(
        "Это всё или переходим к следующему шагу?",
        reply_markup=finalization_kb
    )


@admin_router.callback_query(F.data.startswith("change_step_delay_cancel_"))
async def change_step_delay_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена изменения задержки шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    parts = callback.data.replace("change_step_delay_cancel_", "").split("_")
    button_id = int(parts[0])
    step_number = int(parts[1])
    
    await _clear_state_preserving_admin(state, callback.from_user.id)
    
    await callback.answer("Отменено")
    
    # Возвращаемся к просмотру шага
    button = await get_button_by_id(button_id)
    if button:
        step = await get_button_step(button_id, step_number)
        if step:
            inline_keyboard = []
            delay = step.get("delay", 0)
            if step_number > 1:
                delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
            ])
            if step_number > 1:
                inline_keyboard.append([
                    InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
            ])
            
            kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await callback.message.answer("Выберите действие:", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("change_step_content_cancel_"))
async def change_step_content_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена изменения содержимого шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    parts = callback.data.replace("change_step_content_cancel_", "").split("_")
    button_id = int(parts[0])
    step_number = int(parts[1])
    
    await _clear_state_preserving_admin(state, callback.from_user.id)
    
    await callback.answer("Отменено")
    
    # Возвращаемся к просмотру шага
    button = await get_button_by_id(button_id)
    if button:
        step = await get_button_step(button_id, step_number)
        if step:
            inline_keyboard = []
            delay = step.get("delay", 0)
            if step_number > 1:
                delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
            ])
            if step_number > 1:
                inline_keyboard.append([
                    InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
            ])
            
            kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await callback.message.answer("Выберите действие:", reply_markup=kb)


@admin_router.callback_query(F.data.startswith("add_step_cancel_"))
async def add_step_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена добавления нового шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    button_id = int(callback.data.replace("add_step_cancel_", ""))
    await _clear_state_preserving_admin(state, callback.from_user.id)
    
    await callback.answer("Отменено")
    
    # Возвращаемся к списку шагов
    from src.bot.database.button_steps import get_button_steps
    steps = await get_button_steps(button_id)
    button = await get_button_by_id(button_id)
    
    if not button:
        await callback.message.answer("❌ Кнопка не найдена.")
        return
    
    inline_keyboard = []
    for i, step in enumerate(steps, 1):
        inline_keyboard.append([
            InlineKeyboardButton(text=f"Шаг {i}", callback_data=f"edit_step_{button_id}_{i}")
        ])
    
    inline_keyboard.append([
        InlineKeyboardButton(text="➕ Добавление нового шага", callback_data=f"add_step_{button_id}")
    ])
    inline_keyboard.append([
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
    ])
    
    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    await callback.message.answer(
        f"Шаги к кнопке <b>{button['text']}</b>",
        reply_markup=kb
    )


@admin_router.callback_query(F.data == "cancel_edit_text")
async def admin_edit_text_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    await _clear_state_preserving_admin(state, callback.from_user.id)
    await callback.answer("Отменено")
    admin_kb = await build_admin_inline_keyboard_with_user_buttons()
    await callback.message.answer(
        "Изменение текста отменено.",
        reply_markup=admin_kb
    )


@admin_router.message(AdminStates.waiting_for_new_text_for_button, F.text)
async def admin_edit_text_save(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("Ошибка: не найден ID кнопки.")
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Текст пустой. Отправь непустой текст.")
        return

    try:
        success = await update_button_text(button_id, new_text)
        await _clear_state_preserving_admin(state, message.from_user.id)

        if success:
            admin_kb = await build_admin_inline_keyboard_with_user_buttons()
            await message.answer(
                f"✅ Текст кнопки успешно изменён на: <b>{new_text}</b>",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Кнопка не найдена или не удалось обновить.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении текста: {e}")
        await _clear_state_preserving_admin(state, message.from_user.id)


@admin_router.callback_query(F.data == "admin_delete_button")
async def admin_delete_button_start(callback: CallbackQuery) -> None:
    """Начало удаления кнопки из админ-панели."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    buttons = await get_all_buttons()
    if not buttons:
        await callback.answer("Нет кнопок для удаления.", show_alert=True)
        return

    # Создаём клавиатуру для выбора кнопки для удаления
    inline_keyboard = []
    for btn in buttons:
        inline_keyboard.append([
            InlineKeyboardButton(
                text=f"🗑️ {btn['text']}",
                callback_data=f"delete_button_{btn['id']}"
            )
        ])
    
    # Кнопка отмены
    inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")
    ])

    await callback.answer()
    await callback.message.answer(
        "Выбери кнопку, которую хочешь удалить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
    )


@admin_router.callback_query(F.data == "cancel_delete")
async def cancel_delete(callback: CallbackQuery) -> None:
    """Отмена удаления кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    await callback.answer("Отменено")
    admin_kb = await build_admin_inline_keyboard_with_user_buttons()
    await callback.message.answer(
        "Удаление отменено.",
        reply_markup=admin_kb
    )


@admin_router.callback_query(F.data.startswith("edit_button_name_"))
async def edit_button_name_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало редактирования названия кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    button_id = int(callback.data.replace("edit_button_name_", ""))
    button = await get_button_by_id(button_id)
    
    if not button:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return

    # Сохраняем админский режим
    await _preserve_admin_mode(state, callback.from_user.id)
    await state.update_data(button_id=button_id)
    await state.set_state(AdminStates.waiting_for_new_button_name)
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_button_name_cancel_{button_id}")]
    ])
    
    await callback.message.answer(
        f"Текущее название кнопки: <b>{button['text']}</b>\n"
        "Отправь новое название кнопки:",
        reply_markup=cancel_kb
    )


@admin_router.message(AdminStates.waiting_for_new_button_name, F.text)
async def edit_button_name_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового названия кнопки."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("Ошибка: не найден ID кнопки.")
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Название пустое. Отправь непустое название.")
        return
    
    # Проверяем длину названия кнопки (максимум 35 символов)
    if len(new_text) > 35:
        await message.answer(f"❌ Название кнопки слишком длинное. Максимум 35 символов. Текущая длина: {len(new_text)} символов.\n\nОтправь название кнопки снова:")
        return

    try:
        success = await update_button_text(button_id, new_text)
        
        if success:
            # Получаем обновленную кнопку для сообщения об успехе
            updated_button = await get_button_by_id(button_id)
            
            # Очищаем состояние, сохраняя админский режим
            await _clear_state_preserving_admin(state, message.from_user.id)
            
            # Явно устанавливаем админский режим (на всякий случай)
            if _is_admin(message.from_user.id):
                await state.update_data(admin_mode=True, user_mode=False)
            
            # Строим клавиатуру для просмотра кнопки (не главное меню)
            button_kb, button_text = await _build_button_view_keyboard(button_id, state, message.from_user.id)
            
            # Отправляем сообщение об успехе вместе с клавиатурой
            if updated_button:
                await message.answer(
                    f"✅ Название кнопки успешно изменено на: <b>{updated_button['text']}</b>\n\n{button_text}",
                    reply_markup=button_kb
                )
            else:
                await message.answer(button_text, reply_markup=button_kb)
        else:
            await message.answer("❌ Кнопка не найдена или не удалось обновить.")
            await _clear_state_preserving_admin(state, message.from_user.id)
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении названия: {e}")
        await _clear_state_preserving_admin(state, message.from_user.id)


@admin_router.callback_query(F.data.startswith("edit_button_message_"))
async def edit_button_message_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало редактирования текста сообщения кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    button_id = int(callback.data.replace("edit_button_message_", ""))
    button = await get_button_by_id(button_id)
    
    if not button:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return

    # Сохраняем админский режим
    await _preserve_admin_mode(state, callback.from_user.id)
    await state.update_data(button_id=button_id)
    await state.set_state(AdminStates.waiting_for_new_message_text)
    await callback.answer()
    
    current_message = button.get("message_text") or "не задан"
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_button_message_cancel_{button_id}")]
    ])
    
    await callback.message.answer(
        f"Текущий текст сообщения: <b>{current_message}</b>\n"
        "Отправь новый текст сообщения:",
        reply_markup=cancel_kb
    )


@admin_router.message(AdminStates.waiting_for_new_message_text, F.text)
async def edit_button_message_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового текста сообщения кнопки."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("Ошибка: не найден ID кнопки.")
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    new_message_text = (message.text or "").strip()
    if not new_message_text:
        await message.answer("Текст пустой. Отправь непустой текст.")
        return

    try:
        success = await update_button_message_text(button_id, new_message_text)
        
        if success:
            # Очищаем состояние, сохраняя админский режим
            await _clear_state_preserving_admin(state, message.from_user.id)
            
            # Убеждаемся, что админский режим установлен перед построением клавиатуры
            if _is_admin(message.from_user.id):
                data = await state.get_data()
                if not data.get("admin_mode", False):
                    await state.update_data(admin_mode=True, user_mode=False)
            
            # Строим клавиатуру для просмотра кнопки (не главное меню)
            button_kb, button_text = await _build_button_view_keyboard(button_id, state, message.from_user.id)
            await message.answer(
                f"✅ Текст сообщения успешно изменён.\n\n{button_text}",
                reply_markup=button_kb
            )
        else:
            await message.answer("❌ Кнопка не найдена или не удалось обновить.")
            await _clear_state_preserving_admin(state, message.from_user.id)
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении текста сообщения: {e}")
        await _clear_state_preserving_admin(state, message.from_user.id)


@admin_router.callback_query(F.data.startswith("delete_button_"))
async def delete_button_handler(callback: CallbackQuery) -> None:
    """Удаление кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    button_id = int(callback.data.replace("delete_button_", ""))
    button = await get_button_by_id(button_id)
    
    if not button:
        await callback.answer("Кнопка не найдена.", show_alert=True)
        return

    try:
        success = await delete_button(button_id)
        await callback.answer("✅ Кнопка удалена", show_alert=True)
        
        admin_kb = await build_admin_inline_keyboard_with_user_buttons()
        await callback.message.answer(
            f"✅ Кнопка <b>{button['text']}</b> успешно удалена.",
            reply_markup=admin_kb
        )
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("add_file_"))
async def add_file_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления файла к кнопке."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    try:
        button_id = int(callback.data.replace("add_file_", ""))
        button = await get_button_by_id(button_id)
        
        if not button:
            await callback.answer("Кнопка не найдена.", show_alert=True)
            return

        await state.update_data(button_id=button_id)
        await state.set_state(AdminStates.waiting_for_file)
        await callback.answer()
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"add_file_cancel_{button_id}")]
        ])
        
        await callback.message.answer(
            f"📎 Отправь файл для кнопки <b>{button['text']}</b>.\n"
            "Поддерживаются: фото, видео, документы, аудио, голосовые сообщения.",
            reply_markup=cancel_kb
        )
    except ValueError:
        await callback.answer("Ошибка: некорректный ID кнопки.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("remove_file_"))
async def remove_file_handler(callback: CallbackQuery) -> None:
    """Удаление файла у кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    try:
        button_id = int(callback.data.replace("remove_file_", ""))
        button = await get_button_by_id(button_id)
        
        if not button:
            await callback.answer("Кнопка не найдена.", show_alert=True)
            return

        if not button.get("file_id"):
            await callback.answer("У кнопки нет файла.", show_alert=True)
            return

        success = await remove_button_file(button_id)
        if success:
            await callback.answer("✅ Файл удален", show_alert=True)
            await callback.message.answer(f"✅ Файл удален у кнопки <b>{button['text']}</b>.")
        else:
            await callback.answer("❌ Ошибка при удалении файла", show_alert=True)
    except ValueError:
        await callback.answer("Ошибка: некорректный ID кнопки.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.message(AdminStates.waiting_for_file, F.photo | F.video | F.document | F.audio | F.voice | F.video_note)
async def handle_file_upload(message: Message, state: FSMContext) -> None:
    """Обработка загруженного файла."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("❌ Ошибка: не указан ID кнопки.")
        await _clear_state_preserving_admin(state, message.from_user.id)
        return

    try:
        file_id = None
        file_type = None

        # Определяем тип файла и получаем file_id
        if message.photo:
            file_id = message.photo[-1].file_id  # Берем самое большое фото
            file_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            file_type = "video"
        elif message.document:
            file_id = message.document.file_id
            file_type = "document"
        elif message.audio:
            file_id = message.audio.file_id
            file_type = "audio"
        elif message.voice:
            file_id = message.voice.file_id
            file_type = "voice"
        elif message.video_note:
            file_id = message.video_note.file_id
            file_type = "video_note"

        if not file_id:
            await message.answer("❌ Не удалось получить файл. Попробуй еще раз.")
            return

        # Сохраняем файл во временное состояние
        await state.update_data(
            current_file_id=file_id,
            current_file_type=file_type
        )
        
        # Спрашиваем нужен ли текст к файлу
        file_caption_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="button_file_caption_yes")],
            [InlineKeyboardButton(text="❌ Нет", callback_data="button_file_caption_no")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"add_file_{button_id}")]
        ])
        
        await message.answer(
            f"✅ Файл получен: {file_type}\n\n"
            "Нужно ли описание к этому файлу?",
            reply_markup=file_caption_kb
        )
        
        await state.set_state(AdminStates.waiting_for_file_caption_for_button)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()


@admin_router.callback_query(F.data == "button_file_caption_yes")
async def button_file_caption_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь хочет добавить текст к файлу существующей кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await callback.answer("Ошибка: не найден ID кнопки.", show_alert=True)
        await state.clear()
        return
    
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"add_file_{button_id}")]
    ])
    
    await callback.message.answer(
        "Отправь текст для файла:",
        reply_markup=cancel_kb
    )
    
    await state.set_state(AdminStates.waiting_for_file_caption_for_button)


@admin_router.callback_query(F.data == "button_file_caption_no")
async def button_file_caption_no(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь не хочет добавлять текст к файлу существующей кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    data = await state.get_data()
    button_id = data.get("button_id")
    file_id = data.get("current_file_id")
    file_type = data.get("current_file_type")
    
    if not button_id or not file_id:
        await callback.answer("Ошибка: не найдены данные.", show_alert=True)
        await state.clear()
        return
    
    # Сохраняем файл в БД без текста
    success = await update_button_file(button_id, file_id, file_type)
    
    if success:
        button = await get_button_by_id(button_id)
        await callback.message.answer(
            f"✅ Файл успешно добавлен к кнопке <b>{button['text']}</b>!\n"
            f"Тип: {file_type}"
        )
    else:
        await callback.message.answer("❌ Ошибка при сохранении файла.")
    
    await state.clear()
    await _preserve_admin_mode(state, callback.from_user.id)
    await state.update_data(admin_mode=True, user_mode=False)
    
    # Возвращаемся к просмотру кнопки
    button_kb, button_text = await _build_button_view_keyboard(button_id, state, callback.from_user.id)
    await callback.message.answer(button_text, reply_markup=button_kb)


@admin_router.message(AdminStates.waiting_for_file_caption_for_button, F.text)
async def button_file_caption_save(message: Message, state: FSMContext) -> None:
    """Сохранение текста для файла существующей кнопки."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    data = await state.get_data()
    button_id = data.get("button_id")
    file_id = data.get("current_file_id")
    file_type = data.get("current_file_type")
    
    if not button_id or not file_id:
        await message.answer("❌ Ошибка: не найдены данные.")
        await state.clear()
        return
    
    caption_text = (message.text or "").strip()
    
    # Сохраняем файл в БД
    success = await update_button_file(button_id, file_id, file_type)
    
    if success:
        # Обновляем текст сообщения кнопки
        await update_button_message_text(button_id, caption_text)
        
        button = await get_button_by_id(button_id)
        await message.answer(
            f"✅ Файл и текст успешно добавлены к кнопке <b>{button['text']}</b>!\n"
            f"Тип: {file_type}\n"
            f"Текст: {caption_text}"
        )
    else:
        await message.answer("❌ Ошибка при сохранении файла.")
    
    await state.clear()
    await _preserve_admin_mode(state, message.from_user.id)
    await state.update_data(admin_mode=True, user_mode=False)
    
    # Возвращаемся к просмотру кнопки
    button_kb, button_text = await _build_button_view_keyboard(button_id, state, message.from_user.id)
    await message.answer(button_text, reply_markup=button_kb)


# ========== НОВЫЕ ОБРАБОТЧИКИ ДЛЯ СОЗДАНИЯ КНОПКИ ПО НОВОМУ СЦЕНАРИЮ ==========

@admin_router.callback_query(F.data == "cancel_button_creation")
async def cancel_button_creation(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена создания кнопки на этапе ввода контента."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    # Получаем parent_id из state, если есть, чтобы вернуться к родительской кнопке
    data = await state.get_data()
    parent_id = data.get("parent_id")
    
    await _clear_state_preserving_admin(state, callback.from_user.id)
    await callback.answer("❌ Создание кнопки отменено")
    
    # Если была родительская кнопка, возвращаемся к ней, иначе в главное меню
    if parent_id:
        # Убеждаемся, что админский режим установлен перед построением клавиатуры
        if _is_admin(callback.from_user.id):
            data = await state.get_data()
            if not data.get("admin_mode", False):
                await state.update_data(admin_mode=True, user_mode=False)
        
        button_kb, button_text = await _build_button_view_keyboard(parent_id, state, callback.from_user.id)
        await callback.message.answer(button_text, reply_markup=button_kb)
    else:
        # Возвращаем в главное меню
        admin_kb = await build_admin_inline_keyboard_with_user_buttons()
        start_text = await get_start_message()
        await callback.message.answer(start_text, reply_markup=admin_kb)


@admin_router.callback_query(F.data == "button_add_delay")
async def button_add_delay_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления задержки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_delay)
    await callback.answer()
    
    # Кнопки назад и отмена
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_delay_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_delay_cancel")]
    ])
    
    await callback.message.answer(
        "⏱️ Укажите задержку в секундах (от 0 до 10):",
        reply_markup=back_kb
    )


@admin_router.callback_query(F.data == "button_delay_back")
async def button_delay_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат из ввода задержки к финализации."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_button_finalization)
    await callback.answer()
    
    # Получаем задержку для следующего шага из состояния
    data = await state.get_data()
    next_delay = data.get("next_delay", 0)
    
    # Показываем клавиатуру финализации
    finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
        [InlineKeyboardButton(text=_get_delay_button_text(next_delay), callback_data="button_add_delay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
    ])
    
    await callback.message.answer(
        "Это всё или переходим к следующему шагу?",
            reply_markup=finalization_kb
        )


@admin_router.message(AdminStates.waiting_for_file_caption, F.text)
async def file_caption_save(message: Message, state: FSMContext) -> None:
    """Сохранение текста для файла."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    caption_text = (message.text or "").strip()
    
    # Получаем текущие шаги и файл из состояния
    data = await state.get_data()
    steps = data.get("steps", [])
    file_id = data.get("current_file_id")
    file_type = data.get("current_file_type", "файл")
    next_delay = data.get("next_delay", 0)
    
    # Добавляем новый шаг с файлом и текстом
    step_number = len(steps) + 1
    steps.append({
        "step_number": step_number,
        "content_type": "file",
        "content_text": caption_text,
        "file_id": file_id,
        "file_type": file_type,
        "delay": next_delay if step_number > 1 else 0  # Задержка только для шагов после первого
    })
    
    # Сохраняем шаги в состояние и сбрасываем задержку для следующего шага
    await state.update_data(steps=steps, next_delay=0)
    
    # Переходим к финализации
    await message.answer(f"✅ {step_number} шаг загружен: Файл: {file_type}")
    
    # Клавиатура для финализации (показываем задержку для следующего шага)
    delay = 0
    finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
        [InlineKeyboardButton(text=_get_delay_button_text(delay), callback_data="button_add_delay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
    ])
    
    await message.answer(
        "Это всё или переходим к следующему шагу?",
        reply_markup=finalization_kb
    )
    
    await state.set_state(AdminStates.waiting_for_button_finalization)


@admin_router.callback_query(F.data == "file_caption_yes")
async def file_caption_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь хочет добавить текст к файлу при создании новой кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="file_caption_cancel")]
    ])
    
    await callback.message.answer(
        "Отправь текст для файла:",
        reply_markup=cancel_kb
    )
    
    # Остаемся в состоянии waiting_for_file_caption для получения текста


@admin_router.callback_query(F.data == "file_caption_skip")
async def file_caption_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропуск текста для файла - переход к финализации."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    # Получаем текущие шаги и файл из состояния
    data = await state.get_data()
    steps = data.get("steps", [])
    file_id = data.get("current_file_id")
    file_type = data.get("current_file_type", "файл")
    next_delay = data.get("next_delay", 0)
    
    # Добавляем новый шаг с файлом без текста
    step_number = len(steps) + 1
    steps.append({
        "step_number": step_number,
        "content_type": "file",
        "content_text": "",
        "file_id": file_id,
        "file_type": file_type,
        "delay": next_delay if step_number > 1 else 0  # Задержка только для шагов после первого
    })
    
    # Сохраняем шаги в состояние и сбрасываем задержку для следующего шага
    await state.update_data(steps=steps, next_delay=0)
    
    await callback.answer()
    await callback.message.answer(f"✅ {step_number} шаг загружен: Файл: {file_type}")
    
    # Клавиатура для финализации (показываем задержку для следующего шага)
    delay = 0
    finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
        [InlineKeyboardButton(text=_get_delay_button_text(delay), callback_data="button_add_delay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
    ])
    
    await callback.message.answer(
        "Это всё или переходим к следующему шагу?",
        reply_markup=finalization_kb
    )
    
    await state.set_state(AdminStates.waiting_for_button_finalization)


@admin_router.callback_query(F.data == "file_caption_cancel")
async def file_caption_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена файла - возврат к вводу контента."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    # Удаляем файл из состояния
    await state.update_data(
        file_id=None,
        file_type=None,
        content_type=None
    )
    
    # Возвращаемся к вводу контента
    data = await state.get_data()
    button_text = data.get("button_text")
    
    await state.set_state(AdminStates.waiting_for_new_button_content)
    await callback.answer("Файл отменен")
    
    # Кнопка отмены
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_button_creation")]
    ])
    
    await callback.message.answer(
        f"Название кнопки: <b>{button_text}</b>\n\n"
        "Отправь текст, фото, видео или документ, который будет приходить по нажатию на кнопку:",
        reply_markup=cancel_kb
    )


@admin_router.message(AdminStates.waiting_for_delay, F.text)
async def button_delay_save(message: Message, state: FSMContext) -> None:
    """Сохранение задержки."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    try:
        delay = int(message.text.strip())
        
        if delay < 0 or delay > 10:
            await message.answer("❌ Задержка должна быть от 0 до 10 секунд. Попробуй еще раз.")
            return
        
        # Сохраняем задержку для следующего шага (который будет создан)
        await state.update_data(next_delay=delay)
        
        # Возвращаемся к финализации
        await state.set_state(AdminStates.waiting_for_button_finalization)
        
        # Получаем данные для отображения задержки
        data = await state.get_data()
        next_delay = data.get("next_delay", delay)  # Используем сохраненную задержку
        
        finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
            [InlineKeyboardButton(text=_get_delay_button_text(next_delay), callback_data="button_add_delay")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
        ])
        
        await message.answer(
            f"✅ Задержка установлена: {delay} секунд (будет применена перед следующим шагом)\n\n"
            "Это всё или переходим к следующему шагу?",
            reply_markup=finalization_kb
        )
    except ValueError:
        await message.answer("❌ Что-то отправлено не так. Укажите число от 0 до 10.")


@admin_router.message(AdminStates.waiting_for_button_finalization, F.text)
async def admin_finalization_text_handler(message: Message, state: FSMContext) -> None:
    """Обработка текста в состоянии финализации - добавление нового шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    content_text = (message.text or "").strip()
    
    # Получаем текущие шаги из состояния
    data = await state.get_data()
    steps = data.get("steps", [])
    next_delay = data.get("next_delay", 0)
    
    # Добавляем новый шаг
    step_number = len(steps) + 1
    steps.append({
        "step_number": step_number,
        "content_type": "text",
        "content_text": content_text,
        "file_id": None,
        "file_type": None,
        "delay": next_delay if step_number > 1 else 0  # Задержка только для шагов после первого
    })
    
    # Сохраняем шаги в состояние и сбрасываем задержку для следующего шага
    await state.update_data(steps=steps, next_delay=0)
    
    await message.answer(f"✅ {step_number} шаг загружен: Текст")
    
    # Клавиатура для финализации (показываем задержку для следующего шага)
    delay = 0
    finalization_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Готово", callback_data="button_finish_creation")],
        [InlineKeyboardButton(text=_get_delay_button_text(delay), callback_data="button_add_delay")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="button_step_back")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="button_cancel_confirm")]
    ])
    
    await message.answer(
        "Это всё или переходим к следующему шагу?",
        reply_markup=finalization_kb
    )


@admin_router.message(AdminStates.waiting_for_button_finalization, F.photo | F.video | F.document | F.audio | F.voice | F.video_note)
async def admin_finalization_file_handler(message: Message, state: FSMContext) -> None:
    """Обработка файла в состоянии финализации - добавление нового шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    # Определяем тип файла и получаем file_id
    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.video_note:
        file_id = message.video_note.file_id
        file_type = "video_note"

    if not file_id:
        await message.answer("❌ Не удалось получить файл. Попробуй еще раз.")
        return

    # Сохраняем файл во временное состояние (для добавления текста)
    await state.update_data(
        current_file_id=file_id,
        current_file_type=file_type
    )
    
    # Спрашиваем нужен ли текст к файлу
    file_caption_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Продолжить", callback_data="file_caption_skip")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="file_caption_cancel")]
    ])
    
    await message.answer(
        "Нужен ли текст к этому файлу?\n"
        "Отправь текст или нажми 'Продолжить' чтобы пропустить.",
        reply_markup=file_caption_kb
    )
    
    await state.set_state(AdminStates.waiting_for_file_caption)


@admin_router.callback_query(F.data == "button_step_back")
async def button_step_back_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат на предыдущий шаг (к вводу контента)."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    data = await state.get_data()
    button_text = data.get("button_text")
    
    await state.set_state(AdminStates.waiting_for_new_button_content)
    await callback.answer()
    
    # Кнопка отмены
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_button_creation")]
    ])
    
    await callback.message.answer(
        f"Название кнопки: <b>{button_text}</b>\n\n"
        "Отправь текст, фото, видео или документ, который будет приходить по нажатию на кнопку:",
        reply_markup=cancel_kb
    )


@admin_router.callback_query(F.data == "button_cancel_confirm")
async def button_cancel_confirm_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение отмены создания кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await state.clear()
    await callback.answer("❌ Создание кнопки отменено")
    
    # Возвращаем в главное меню
    admin_kb = await build_admin_inline_keyboard_with_user_buttons()
    start_text = await get_start_message()
    await callback.message.answer(start_text, reply_markup=admin_kb)


async def finish_button_creation(message: Message, state: FSMContext) -> None:
    """Завершение создания кнопки и сохранение в БД."""
    data = await state.get_data()
    button_text = data.get("button_text")
    steps = data.get("steps", [])
    parent_id = data.get("parent_id")
    user_id = message.from_user.id
    
    # Сохраняем админский режим перед очисткой
    await _preserve_admin_mode(state, user_id)
    
    if not button_text:
        await message.answer("Ошибка: не найден текст кнопки.")
        await state.clear()
        # Восстанавливаем админский режим
        if _is_admin(user_id):
            await state.update_data(admin_mode=True, user_mode=False)
        return
    
    if not steps:
        await message.answer("Ошибка: не добавлено ни одного шага.")
        return
    
    try:
        # Создаем кнопку в БД (без задержки, она будет в шагах)
        button_id = await add_button_to_db(button_text, "", parent_id, 0)
        
        # Сохраняем все шаги в БД
        for step in steps:
            await add_button_step(
                button_id=button_id,
                step_number=step["step_number"],
                content_type=step["content_type"],
                content_text=step.get("content_text", ""),
                file_id=step.get("file_id"),
                file_type=step.get("file_type"),
                delay=step.get("delay", 0)
            )
        
        # Показываем результат
        if parent_id:
            from src.bot.database.start_message import get_start_message
            
            parent_button = await get_button_by_id(parent_id)
            if parent_button:
                steps_count = len(steps)
                
                # Очищаем состояние, сохраняя админский режим
                await _clear_state_preserving_admin(state, user_id)
                
                # Явно устанавливаем админский режим (на всякий случай)
                if _is_admin(user_id):
                    await state.update_data(admin_mode=True, user_mode=False)
                
                # Строим клавиатуру ДО отправки сообщения об успехе
                admin_kb, admin_text = await _build_button_view_keyboard(parent_id, state, user_id)
                
                # Отправляем сообщение об успехе вместе с клавиатурой
                await message.answer(
                    f"✅ Кнопка <b>{button_text}</b> с {steps_count} шагами добавлена внутрь кнопки <b>{parent_button['text']}</b>.\n\n{admin_text}",
                    reply_markup=admin_kb
                )
                return
        
        # Если кнопка в главном меню
        buttons = await get_all_buttons()
        preview = "\n".join(f"- {b['text']} (ID: {b['id']})" for b in buttons) if buttons else "пока нет кнопок"
        
        admin_kb = await build_admin_inline_keyboard_with_user_buttons()
        steps_count = len(steps)
        await message.answer(
            f"✅ Кнопка <b>{button_text}</b> с {steps_count} шагами добавлена (ID: {button_id}).\n"
            "Текущий набор ваших сконструированных кнопок:\n"
            f"{preview}",
            reply_markup=admin_kb
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении кнопки: {e}")
        await state.clear()
        # Восстанавливаем админский режим
        if _is_admin(user_id):
            await state.update_data(admin_mode=True, user_mode=False)


# ВАЖНО: Этот обработчик должен быть ПОСЛЕ edit_step_, так как edit_step_ более специфичен
# Используем точное совпадение вместо startswith, чтобы не перехватывать edit_step_
@admin_router.callback_query(F.data.regexp(r"^edit_steps_\d+$"))
async def edit_steps_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Показ списка шагов кнопки для редактирования."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    try:
        button_id = int(callback.data.replace("edit_steps_", ""))
        button = await get_button_by_id(button_id)
        
        if not button:
            await callback.answer("Кнопка не найдена.", show_alert=True)
            return
        
        # Очищаем стейты при возврате к списку шагов
        await state.clear()
        await _preserve_admin_mode(state, callback.from_user.id)
        await state.update_data(admin_mode=True, user_mode=False)
        
        # Получаем все шаги кнопки
        steps = await get_button_steps(button_id)
        
        await callback.answer()
        
        # Формируем клавиатуру
        inline_keyboard = []
        
        # Добавляем кнопки для каждого шага
        for step in steps:
            step_number = step.get("step_number", 0)
            if step_number == 0:
                import logging
                logging.error(f"Invalid step_number in step: {step}")
                continue
            inline_keyboard.append([
                InlineKeyboardButton(text=f"Шаг {step_number}", callback_data=f"edit_step_{button_id}_{step_number}")
            ])
        
        # Кнопка "Добавление нового шага"
        inline_keyboard.append([
            InlineKeyboardButton(text="➕ Добавление нового шага", callback_data=f"add_step_{button_id}")
        ])
        
        # Кнопка "Назад" - возвращаемся к просмотру кнопки
        # Если шагов нет, возвращаемся в главное меню
        if not steps:
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
            ])
        else:
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(button["callback_data"]))
            ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        
        if not steps:
            # Если шагов нет, показываем сообщение и возвращаемся в главное меню
            await callback.message.answer(
                f"✅ Все шаги кнопки <b>{button['text']}</b> удалены.\n\n"
                "Шагов не осталось. Вы можете добавить новый шаг или вернуться в главное меню.",
                reply_markup=kb
            )
        else:
            await callback.message.answer(
                f"Шаги к кнопке <b>{button['text']}</b>",
                reply_markup=kb
            )
    except ValueError:
        await callback.answer("Ошибка: некорректный ID кнопки.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("add_step_"))
async def add_step_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления нового шага к существующей кнопке."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    try:
        button_id = int(callback.data.replace("add_step_", ""))
        button = await get_button_by_id(button_id)
        
        if not button:
            await callback.answer("Кнопка не найдена.", show_alert=True)
            return
        
        await state.update_data(adding_step_button_id=button_id)
        await state.set_state(AdminStates.waiting_for_new_step_content)
        await callback.answer()
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_steps_{button_id}")]
        ])
        
        await callback.message.answer(
            "Отправь текст, фото, видео или документ для нового шага:",
            reply_markup=cancel_kb
        )
    except ValueError:
        await callback.answer("Ошибка: некорректный ID кнопки.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.message(AdminStates.waiting_for_new_step_content, F.text)
async def add_step_text_handler(message: Message, state: FSMContext) -> None:
    """Обработка текста для нового шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    content_text = (message.text or "").strip()
    
    data = await state.get_data()
    button_id = data.get("adding_step_button_id")
    
    if not button_id:
        await message.answer("❌ Ошибка: не найден ID кнопки.")
        await state.clear()
        return
    
    # Сохраняем контент во временное состояние
    await state.update_data(
        new_step_content_type="text",
        new_step_content_text=content_text,
        new_step_file_id=None,
        new_step_file_type=None
    )
    
    # Переходим к выбору позиции
    steps = await get_button_steps(button_id)
    max_position = len(steps) + 1
    
    await message.answer(
        f"На какое место вы хотите поставить шаг? (введите число от 1 до {max_position})"
    )
    
    await state.set_state(AdminStates.waiting_for_new_step_position)


@admin_router.message(AdminStates.waiting_for_new_step_content, F.photo | F.video | F.document | F.audio | F.voice | F.video_note)
async def add_step_file_handler(message: Message, state: FSMContext) -> None:
    """Обработка файла для нового шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    # Определяем тип файла и получаем file_id
    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.video_note:
        file_id = message.video_note.file_id
        file_type = "video_note"

    if not file_id:
        await message.answer("❌ Не удалось получить файл. Попробуй еще раз.")
        return
    
    data = await state.get_data()
    button_id = data.get("adding_step_button_id")
    
    if not button_id:
        await message.answer("❌ Ошибка: не найден ID кнопки.")
        await state.clear()
        return
    
    # Сохраняем файл во временное состояние
    await state.update_data(
        new_step_file_id=file_id,
        new_step_file_type=file_type
    )
    
    # Спрашиваем нужен ли текст к файлу
    file_caption_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="new_step_file_caption_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="new_step_file_caption_no")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"add_step_{button_id}")]
    ])
    
    await message.answer(
        f"✅ Файл получен: {file_type}\n\n"
        "Нужно ли описание к этому файлу?",
        reply_markup=file_caption_kb
    )
    
    await state.set_state(AdminStates.waiting_for_new_step_file_caption)


@admin_router.callback_query(F.data == "new_step_file_caption_yes")
async def new_step_file_caption_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь хочет добавить текст к файлу."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    data = await state.get_data()
    button_id = data.get("adding_step_button_id")
    
    if not button_id:
        await callback.answer("Ошибка: не найден ID кнопки.", show_alert=True)
        await state.clear()
        return
    
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_steps_{button_id}")]
    ])
    
    await callback.message.answer(
        "Отправь текст для файла:",
        reply_markup=cancel_kb
    )
    
    await state.set_state(AdminStates.waiting_for_new_step_file_caption)


@admin_router.message(AdminStates.waiting_for_new_step_file_caption, F.text)
async def new_step_file_caption_save(message: Message, state: FSMContext) -> None:
    """Сохранение текста для файла нового шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    caption_text = (message.text or "").strip()
    
    # Сохраняем контент
    await state.update_data(
        new_step_content_type="file",
        new_step_content_text=caption_text
    )
    
    # Переходим к выбору позиции
    data = await state.get_data()
    button_id = data.get("adding_step_button_id")
    
    if not button_id:
        await message.answer("❌ Ошибка: не найден ID кнопки.")
        await state.clear()
        return
    
    steps = await get_button_steps(button_id)
    max_position = len(steps) + 1
    
    await message.answer(
        f"На какое место вы хотите поставить шаг? (введите число от 1 до {max_position})"
    )
    
    await state.set_state(AdminStates.waiting_for_new_step_position)


@admin_router.callback_query(F.data == "new_step_file_caption_no")
async def new_step_file_caption_no(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь не хочет добавлять текст к файлу."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    # Сохраняем контент без текста
    await state.update_data(
        new_step_content_type="file",
        new_step_content_text=""
    )
    
    data = await state.get_data()
    button_id = data.get("adding_step_button_id")
    
    if not button_id:
        await callback.answer("Ошибка: не найден ID кнопки.", show_alert=True)
        await state.clear()
        return
    
    await callback.answer()
    
    # Переходим к выбору позиции
    steps = await get_button_steps(button_id)
    max_position = len(steps) + 1
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"add_step_cancel_{button_id}")]
    ])
    
    await callback.message.answer(
        f"На какое место вы хотите поставить шаг? (введите число от 1 до {max_position})",
        reply_markup=cancel_kb
    )
    
    await state.set_state(AdminStates.waiting_for_new_step_position)


@admin_router.message(AdminStates.waiting_for_new_step_position, F.text)
async def new_step_position_save(message: Message, state: FSMContext) -> None:
    """Сохранение позиции нового шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    try:
        position = int(message.text.strip())
        
        data = await state.get_data()
        button_id = data.get("adding_step_button_id")
        
        if not button_id:
            await message.answer("❌ Ошибка: не найден ID кнопки.")
            await state.clear()
            return
        
        # Получаем текущие шаги для проверки диапазона
        steps = await get_button_steps(button_id)
        max_position = len(steps) + 1
        
        if position < 1 or position > max_position:
            await message.answer(f"❌ Позиция должна быть от 1 до {max_position}. Попробуй еще раз.")
            return
        
        
        # Получаем данные нового шага
        content_type = data.get("new_step_content_type")
        content_text = data.get("new_step_content_text", "")
        file_id = data.get("new_step_file_id")
        file_type = data.get("new_step_file_type")
        
        if not content_type:
            await message.answer("❌ Ошибка: не найден тип контента.")
            await state.clear()
            return
        
        # Получаем данные нового шага
        content_type = data.get("new_step_content_type")
        content_text = data.get("new_step_content_text", "")
        file_id = data.get("new_step_file_id")
        file_type = data.get("new_step_file_type")
        
        if not content_type:
            await message.answer("❌ Ошибка: не найден тип контента.")
            await state.clear()
            return
        
        # Показываем подтверждение
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить добавление", callback_data=f"confirm_add_step_{button_id}_{position}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"edit_steps_{button_id}")]
        ])
        
        await message.answer(
            f"Вы хотите добавить шаг на позицию <b>{position}</b>.\n"
            "Подтвердите добавление:",
            reply_markup=confirm_kb
        )
    except ValueError:
        await message.answer("❌ Что-то отправлено не так. Укажите число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()


@admin_router.callback_query(F.data.startswith("confirm_add_step_"))
async def confirm_add_step_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение добавления шага на позицию."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    try:
        # Извлекаем button_id и position из callback_data
        parts = callback.data.replace("confirm_add_step_", "").split("_")
        button_id = int(parts[0])
        position = int(parts[1])
        
        data = await state.get_data()
        
        # Получаем данные нового шага
        content_type = data.get("new_step_content_type")
        content_text = data.get("new_step_content_text", "")
        file_id = data.get("new_step_file_id")
        file_type = data.get("new_step_file_type")
        
        if not content_type:
            await callback.answer("Ошибка: не найден тип контента.", show_alert=True)
            await state.clear()
            return
        
        # Вставляем шаг на указанную позицию
        step_id = await insert_step_at_position(
            button_id=button_id,
            position=position,
            content_type=content_type,
            content_text=content_text if content_type == "text" or (content_type == "file" and content_text) else None,
            file_id=file_id if content_type == "file" else None,
            file_type=file_type if content_type == "file" else None,
            delay=0  # Задержка для нового шага будет 0, можно изменить позже
        )
        
        await state.clear()
        await callback.answer("✅ Шаг добавлен", show_alert=True)
        
        # Возвращаемся к списку шагов
        button = await get_button_by_id(button_id)
        if button:
            updated_steps = await get_button_steps(button_id)
            
            inline_keyboard = []
            for step in updated_steps:
                step_num = step.get("step_number", 0)
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"Шаг {step_num}", callback_data=f"edit_step_{button_id}_{step_num}")
                ])
            
            inline_keyboard.append([
                InlineKeyboardButton(text="➕ Добавление нового шага", callback_data=f"add_step_{button_id}")
            ])
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(button["callback_data"]))
            ])
            
            kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await callback.message.answer(
                f"✅ Шаг добавлен на позицию {position}. Все последующие шаги перенумерованы.\n\n"
                f"Шаги к кнопке <b>{button['text']}</b>",
                reply_markup=kb
            )
    except (ValueError, IndexError):
        await callback.answer("Ошибка: некорректные данные.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        await state.clear()


# ВАЖНО: edit_step_ должен быть ПЕРЕД edit_steps_, так как edit_step_ более специфичен
# иначе edit_steps_ может перехватывать вызовы для edit_step_
@admin_router.callback_query(F.data.startswith("edit_step_"))
async def edit_step_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Просмотр и редактирование конкретного шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    # Сохраняем админский режим
    await _preserve_admin_mode(state, callback.from_user.id)
    await state.update_data(admin_mode=True, user_mode=False)
    
    try:
        # Извлекаем button_id и step_number из callback_data
        # Формат: edit_step_{button_id}_{step_number}
        data_str = callback.data.replace("edit_step_", "")
        
        import logging
        logging.info(f"edit_step_handler: callback_data={callback.data}, data_str={data_str}")
        
        # Разделяем по последнему подчеркиванию (step_number всегда последний)
        last_underscore = data_str.rfind("_")
        if last_underscore == -1:
            # Если нет подчеркивания, значит это может быть только step_number (для шага 1 с button_id без подчеркиваний)
            # Но это маловероятно, так как button_id обычно число
            raise ValueError(f"Invalid callback data format: {callback.data}")
        
        button_id_str = data_str[:last_underscore]
        step_number_str = data_str[last_underscore + 1:]
        
        logging.info(f"Parsed: button_id_str='{button_id_str}', step_number_str='{step_number_str}'")
        
        button_id = int(button_id_str)
        step_number = int(step_number_str)
        
        logging.info(f"edit_step_handler: button_id={button_id}, step_number={step_number}")
        
        button = await get_button_by_id(button_id)
        if not button:
            await callback.answer("Кнопка не найдена.", show_alert=True)
            logging.error(f"Button not found: button_id={button_id}")
            return
        
        step = await get_button_step(button_id, step_number)
        if not step:
            await callback.answer("Шаг не найден.", show_alert=True)
            logging.error(f"Step not found: button_id={button_id}, step_number={step_number}")
            # Попробуем получить все шаги для отладки
            all_steps = await get_button_steps(button_id)
            logging.error(f"All steps for button {button_id}: {all_steps}")
            return
        
        logging.info(f"Step found: {step}")
        
        await callback.answer()
        
        # Показываем содержимое шага
        content_type = step.get("content_type")
        content_text = step.get("content_text", "")
        file_id = step.get("file_id")
        file_type = step.get("file_type")
        delay = step.get("delay", 0)
        
        logging.info(f"Sending step content: content_type={content_type}, file_type={file_type}, has_file_id={bool(file_id)}, has_content_text={bool(content_text)}")
        
        try:
            # Отправляем содержимое шага
            if content_type == "text" and content_text:
                logging.info("Sending text step")
                await callback.message.answer(f"📝 <b>Шаг {step_number}</b>\n\n{content_text}")
            elif content_type == "file" and file_id:
                logging.info(f"Sending file step: file_type={file_type}")
                try:
                    if file_type == "photo":
                        # Telegram ограничивает caption до 1024 символов
                        MAX_CAPTION_LENGTH = 1024
                        step_header = f"📎 <b>Шаг {step_number}</b>"
                        text_to_send_separately = None
                        
                        if content_text:
                            full_caption = f"{step_header}\n\n{content_text}"
                            if len(full_caption) <= MAX_CAPTION_LENGTH:
                                caption = full_caption
                            else:
                                # Если текст длиннее, отправляем заголовок с файлом, а текст отдельным сообщением
                                caption = step_header
                                text_to_send_separately = content_text
                        else:
                            caption = step_header
                        
                        logging.info(f"Sending photo with caption length: {len(caption)}")
                        await callback.message.answer_photo(photo=file_id, caption=caption)
                        if text_to_send_separately:
                            await callback.message.answer(text_to_send_separately)
                    elif file_type == "video":
                        caption = f"📎 <b>Шаг {step_number}</b>\n\n{content_text}" if content_text else f"📎 <b>Шаг {step_number}</b>"
                        await callback.message.answer_video(video=file_id, caption=caption)
                    elif file_type == "document":
                        caption = f"📎 <b>Шаг {step_number}</b>\n\n{content_text}" if content_text else f"📎 <b>Шаг {step_number}</b>"
                        await callback.message.answer_document(document=file_id, caption=caption)
                    elif file_type == "audio":
                        caption = f"📎 <b>Шаг {step_number}</b>\n\n{content_text}" if content_text else f"📎 <b>Шаг {step_number}</b>"
                        await callback.message.answer_audio(audio=file_id, caption=caption)
                    elif file_type == "voice":
                        caption = f"📎 <b>Шаг {step_number}</b>\n\n{content_text}" if content_text else f"📎 <b>Шаг {step_number}</b>"
                        await callback.message.answer_voice(voice=file_id, caption=caption)
                    elif file_type == "video_note":
                        await callback.message.answer_video_note(video_note=file_id)
                        await callback.message.answer(f"📎 <b>Шаг {step_number}</b>")
                    else:
                        caption = f"📎 <b>Шаг {step_number}</b>\n\n{content_text}" if content_text else f"📎 <b>Шаг {step_number}</b>"
                        await callback.message.answer_document(document=file_id, caption=caption)
                except TelegramBadRequest as e:
                    logging.error(f"Ошибка при отправке файла (просмотр шага {step_number}): {e}. file_id={file_id}, file_type={file_type}")
                    # Отправляем сообщение об ошибке с текстом, если он есть
                    error_msg = f"⚠️ <b>Шаг {step_number}</b>\n\nНе удалось отправить файл (файл больше не доступен)."
                    if content_text:
                        error_msg += f"\n\n{content_text}"
                    await callback.message.answer(error_msg)
            else:
                logging.info("Sending empty step message")
                await callback.message.answer(f"📝 <b>Шаг {step_number}</b>\n\n(Пустой шаг)")
        except Exception as e:
            logging.error(f"Error sending step content: {e}", exc_info=True)
            await callback.message.answer(f"❌ Ошибка при отправке содержимого шага: {e}")
        
        # Формируем клавиатуру
        inline_keyboard = []
        
        # Если это не первый шаг, показываем кнопки редактирования
        if step_number > 1:
            # Показываем задержку, если она есть
            delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
            inline_keyboard.append([
                InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
            ])
        
        # Кнопки для изменения содержимого (для всех шагов)
        inline_keyboard.append([
            InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
        ])
        
        # Кнопка удаления (для всех шагов)
        inline_keyboard.append([
            InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
        ])
        
        # Кнопка "Назад"
        inline_keyboard.append([
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await callback.message.answer("Выберите действие:", reply_markup=kb)
        
    except (ValueError, IndexError):
        await callback.answer("Ошибка: некорректные данные.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


# Обработчик для завершения создания кнопки (когда пользователь не добавляет задержку)
# Это будет вызываться через callback или можно добавить отдельную кнопку "Готово"
# Пока добавлю обработчик для состояния финализации, который будет завершать создание
@admin_router.callback_query(F.data == "button_finish_creation")
async def button_finish_creation_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Завершение создания кнопки."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    await callback.answer()
    await finish_button_creation(callback.message, state)


@admin_router.callback_query(F.data.startswith("delete_step_"))
async def delete_step_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Удаление шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    try:
        parts = callback.data.replace("delete_step_", "").split("_")
        button_id = int(parts[0])
        step_number = int(parts[1])
        
        button = await get_button_by_id(button_id)
        if not button:
            await callback.answer("Кнопка не найдена.", show_alert=True)
            return
        
        success = await delete_button_step(button_id, step_number)
        
        if success:
            await callback.answer("✅ Шаг удален", show_alert=True)
            # Возвращаемся к списку шагов
            steps = await get_button_steps(button_id)
            
            inline_keyboard = []
            for step in steps:
                step_num = step.get("step_number", 0)
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"Шаг {step_num}", callback_data=f"edit_step_{button_id}_{step_num}")
                ])
            
            inline_keyboard.append([
                InlineKeyboardButton(text="➕ Добавление нового шага", callback_data=f"add_step_{button_id}")
            ])
            
            # Если шагов нет, возвращаемся в главное меню
            if not steps:
                inline_keyboard.append([
                    InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
                ])
                kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
                await callback.message.answer(
                    f"✅ Шаг {step_number} удален.\n\n"
                    f"✅ Все шаги кнопки <b>{button['text']}</b> удалены.\n\n"
                    "Шагов не осталось. Вы можете добавить новый шаг или вернуться в главное меню.",
                    reply_markup=kb
                )
            else:
                inline_keyboard.append([
                    InlineKeyboardButton(text="◀️ Назад", callback_data=_truncate_callback_data(button["callback_data"]))
                ])
                kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
                await callback.message.answer(
                    f"✅ Шаг {step_number} удален. Все последующие шаги перенумерованы.\n\n"
                    f"Шаги к кнопке <b>{button['text']}</b>",
                    reply_markup=kb
                )
        else:
            await callback.answer("❌ Ошибка при удалении шага", show_alert=True)
    except (ValueError, IndexError):
        await callback.answer("Ошибка: некорректные данные.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(F.data.startswith("change_step_delay_"))
async def change_step_delay_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало изменения задержки шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    try:
        parts = callback.data.replace("change_step_delay_", "").split("_")
        button_id = int(parts[0])
        step_number = int(parts[1])
        
        await state.update_data(editing_button_id=button_id, editing_step_number=step_number)
        await state.set_state(AdminStates.waiting_for_step_delay)
        await callback.answer()
        
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_step_{button_id}_{step_number}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"change_step_delay_cancel_{button_id}_{step_number}")]
        ])
        
        await callback.message.answer(
            "⏱️ Укажите задержку в секундах (от 0 до 10):",
            reply_markup=back_kb
        )
    except (ValueError, IndexError):
        await callback.answer("Ошибка: некорректные данные.", show_alert=True)


@admin_router.message(AdminStates.waiting_for_step_delay, F.text)
async def change_step_delay_save(message: Message, state: FSMContext) -> None:
    """Сохранение новой задержки шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    try:
        delay = int(message.text.strip())
        
        if delay < 0 or delay > 10:
            await message.answer("❌ Задержка должна быть от 0 до 10 секунд. Попробуй еще раз.")
            return
        
        data = await state.get_data()
        button_id = data.get("editing_button_id")
        step_number = data.get("editing_step_number")
        
        if not button_id or not step_number:
            await message.answer("❌ Ошибка: не найдены данные шага.")
            await state.clear()
            return
        
        success = await update_step_delay(button_id, step_number, delay)
        
        if success:
            await message.answer(f"✅ Задержка шага {step_number} обновлена: {delay} секунд")
            await state.clear()
            
            # Возвращаемся к просмотру шага
            button = await get_button_by_id(button_id)
            if button:
                step = await get_button_step(button_id, step_number)
                if step:
                    inline_keyboard = []
                    if step_number > 1:
                        delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
                        inline_keyboard.append([
                            InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
                        ])
                    inline_keyboard.append([
                        InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
                    ])
                    if step_number > 1:
                        inline_keyboard.append([
                            InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
                        ])
                    inline_keyboard.append([
                        InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
                    ])
                    
                    kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
                    await message.answer("Выберите действие:", reply_markup=kb)
        else:
            await message.answer("❌ Ошибка при обновлении задержки.")
            await state.clear()
    except ValueError:
        await message.answer("❌ Что-то отправлено не так. Укажите число от 0 до 10.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()


@admin_router.callback_query(F.data.startswith("change_step_content_"))
async def change_step_content_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало изменения содержимого шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    try:
        parts = callback.data.replace("change_step_content_", "").split("_")
        button_id = int(parts[0])
        step_number = int(parts[1])
        
        await state.update_data(editing_button_id=button_id, editing_step_number=step_number)
        await state.set_state(AdminStates.waiting_for_step_text)
        await callback.answer()
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_step_{button_id}_{step_number}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"change_step_content_cancel_{button_id}_{step_number}")]
        ])
        
        await callback.message.answer(
            "Отправь новый текст, фото, видео или документ для этого шага:",
            reply_markup=cancel_kb
        )
    except (ValueError, IndexError):
        await callback.answer("Ошибка: некорректные данные.", show_alert=True)


@admin_router.message(AdminStates.waiting_for_step_text, F.text)
async def change_step_text_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового текста для шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    content_text = (message.text or "").strip()
    
    data = await state.get_data()
    button_id = data.get("editing_button_id")
    step_number = data.get("editing_step_number")
    
    if not button_id or not step_number:
        await message.answer("❌ Ошибка: не найдены данные шага.")
        await state.clear()
        return
    
    # Получаем текущий шаг, чтобы сохранить тип контента
    step = await get_button_step(button_id, step_number)
    if not step:
        await message.answer("❌ Шаг не найден.")
        await state.clear()
        return
    
    # Обновляем содержимое шага (удаляем файл, если был)
    success = await update_step_content(
        button_id=button_id,
        step_number=step_number,
        content_text=content_text,
        file_id="",  # Пустая строка для удаления файла
        file_type=""  # Пустая строка для удаления типа файла
    )
    
    if success:
        await message.answer(f"✅ Текст шага {step_number} обновлен.")
        await state.clear()
        
        # Возвращаемся к просмотру шага
        button = await get_button_by_id(button_id)
        if button:
            updated_step = await get_button_step(button_id, step_number)
            if updated_step:
                inline_keyboard = []
                delay = updated_step.get("delay", 0)
                if step_number > 1:
                    delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
                    inline_keyboard.append([
                        InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
                    ])
                inline_keyboard.append([
                    InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
                ])
                if step_number > 1:
                    inline_keyboard.append([
                        InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
                    ])
                inline_keyboard.append([
                    InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
                ])
                
                kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
                await message.answer("Выберите действие:", reply_markup=kb)
    else:
        await message.answer("❌ Ошибка при обновлении текста.")
        await state.clear()


@admin_router.message(AdminStates.waiting_for_step_text, F.photo | F.video | F.document | F.audio | F.voice | F.video_note)
async def change_step_file_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового файла для шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    # Определяем тип файла и получаем file_id
    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    elif message.document:
        file_id = message.document.file_id
        file_type = "document"
    elif message.audio:
        file_id = message.audio.file_id
        file_type = "audio"
    elif message.voice:
        file_id = message.voice.file_id
        file_type = "voice"
    elif message.video_note:
        file_id = message.video_note.file_id
        file_type = "video_note"

    if not file_id:
        await message.answer("❌ Не удалось получить файл. Попробуй еще раз.")
        return
    
    data = await state.get_data()
    button_id = data.get("editing_button_id")
    step_number = data.get("editing_step_number")
    
    if not button_id or not step_number:
        await message.answer("❌ Ошибка: не найдены данные шага.")
        await state.clear()
        return
    
    # Сохраняем файл во временное состояние
    await state.update_data(
        editing_file_id=file_id,
        editing_file_type=file_type
    )
    
    # Спрашиваем нужен ли текст к файлу
    file_caption_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="step_file_caption_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="step_file_caption_no")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"change_step_content_{button_id}_{step_number}")]
    ])
    
    await message.answer(
        f"✅ Файл получен: {file_type}\n\n"
        "Нужно ли описание к этому файлу?",
        reply_markup=file_caption_kb
    )
    
    await state.set_state(AdminStates.waiting_for_step_file_caption)


@admin_router.callback_query(F.data == "step_file_caption_yes")
async def step_file_caption_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь хочет добавить текст к файлу при изменении шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    data = await state.get_data()
    button_id = data.get("editing_button_id")
    step_number = data.get("editing_step_number")
    
    if not button_id or not step_number:
        await callback.answer("Ошибка: не найдены данные шага.", show_alert=True)
        await state.clear()
        return
    
    await callback.answer()
    
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"change_step_content_{button_id}_{step_number}")]
    ])
    
    await callback.message.answer(
        "Отправь текст для файла:",
        reply_markup=cancel_kb
    )
    
    # Остаемся в состоянии waiting_for_step_file_caption для получения текста


@admin_router.callback_query(F.data == "step_file_caption_no")
async def step_file_caption_no(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь не хочет добавлять текст к файлу при изменении шага."""
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return
    
    data = await state.get_data()
    button_id = data.get("editing_button_id")
    step_number = data.get("editing_step_number")
    file_id = data.get("editing_file_id")
    file_type = data.get("editing_file_type")
    
    if not button_id or not step_number or not file_id:
        await callback.answer("Ошибка: не найдены данные.", show_alert=True)
        await state.clear()
        return
    
    # Обновляем содержимое шага без текста
    success = await update_step_content(
        button_id=button_id,
        step_number=step_number,
        content_text="",
        file_id=file_id,
        file_type=file_type
    )
    
    if success:
        await callback.message.answer(f"✅ Файл шага {step_number} обновлен: {file_type}")
    else:
        await callback.message.answer("❌ Ошибка при обновлении файла.")
    
    await state.clear()
    await _preserve_admin_mode(state, callback.from_user.id)
    await state.update_data(admin_mode=True, user_mode=False)
    
    # Возвращаемся к просмотру шага
    button = await get_button_by_id(button_id)
    if button:
        updated_step = await get_button_step(button_id, step_number)
        if updated_step:
            inline_keyboard = []
            delay = updated_step.get("delay", 0)
            if step_number > 1:
                delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
            ])
            if step_number > 1:
                inline_keyboard.append([
                    InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
            ])
            
            kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await callback.message.answer("Выберите действие:", reply_markup=kb)


@admin_router.message(AdminStates.waiting_for_step_file_caption, F.text)
async def step_file_caption_save(message: Message, state: FSMContext) -> None:
    """Сохранение текста для файла при изменении шага."""
    if not _is_admin(message.from_user.id):
        await _clear_state_preserving_admin(state, message.from_user.id)
        return
    
    data = await state.get_data()
    button_id = data.get("editing_button_id")
    step_number = data.get("editing_step_number")
    file_id = data.get("editing_file_id")
    file_type = data.get("editing_file_type")
    
    if not button_id or not step_number or not file_id:
        await message.answer("❌ Ошибка: не найдены данные.")
        await state.clear()
        return
    
    caption_text = (message.text or "").strip()
    
    # Обновляем содержимое шага с текстом
    success = await update_step_content(
        button_id=button_id,
        step_number=step_number,
        content_text=caption_text,
        file_id=file_id,
        file_type=file_type
    )
    
    if success:
        await message.answer(f"✅ Файл и текст шага {step_number} обновлены: {file_type}\nТекст: {caption_text}")
    else:
        await message.answer("❌ Ошибка при обновлении файла.")
    
    await state.clear()
    await _preserve_admin_mode(state, message.from_user.id)
    await state.update_data(admin_mode=True, user_mode=False)
    
    # Возвращаемся к просмотру шага
    button = await get_button_by_id(button_id)
    if button:
        updated_step = await get_button_step(button_id, step_number)
        if updated_step:
            inline_keyboard = []
            delay = updated_step.get("delay", 0)
            if step_number > 1:
                delay_text = f" (задержка: {delay} сек)" if delay > 0 else ""
                inline_keyboard.append([
                    InlineKeyboardButton(text=f"⏱️ Изменить задержку{delay_text}", callback_data=f"change_step_delay_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="✏️ Изменить текст", callback_data=f"change_step_content_{button_id}_{step_number}")
            ])
            if step_number > 1:
                inline_keyboard.append([
                    InlineKeyboardButton(text="🗑️ Удалить шаг", callback_data=f"delete_step_{button_id}_{step_number}")
                ])
            inline_keyboard.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_steps_{button_id}")
            ])
            
            kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
            await message.answer("Выберите действие:", reply_markup=kb)

