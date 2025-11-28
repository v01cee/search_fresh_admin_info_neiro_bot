from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.bot.config import get_config
from src.bot.keyboards.common import admin_inline_keyboard
from src.bot.database.buttons import (
    add_button_to_db, get_all_buttons, update_button_text,
    update_button_message_text, delete_button, get_button_by_id
)
from src.bot.services.menu_constructor import build_admin_inline_keyboard_with_user_buttons


admin_router = Router(name="admin")


class AdminStates(StatesGroup):
    waiting_for_new_button_text = State()
    waiting_for_new_button_message = State()
    waiting_for_button_selection_to_edit = State()
    waiting_for_new_text_for_button = State()
    waiting_for_new_button_name = State()
    waiting_for_new_message_text = State()
    waiting_for_new_start_message = State()


def _is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


@admin_router.message(Command("admin"))
async def admin_entry(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("У вас нет прав для входа в админ-панель.")
        return

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
        # Очищаем предыдущее состояние
        await state.clear()
        
        parent_id_str = callback.data.replace("admin_add_button_", "")
        if not parent_id_str:
            await callback.answer("Ошибка: не указан ID родительской кнопки.", show_alert=True)
            return
        
        parent_id = int(parent_id_str)
        await state.update_data(parent_id=parent_id)
        await state.set_state(AdminStates.waiting_for_new_button_text)
        await callback.answer()
        await callback.message.answer("Отправь название кнопки:")
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

    await state.update_data(parent_id=None)
    await state.set_state(AdminStates.waiting_for_new_button_text)
    await callback.answer()
    await callback.message.answer("Отправь название кнопки:")


@admin_router.message(AdminStates.waiting_for_new_button_text, F.text)
async def admin_add_button_text_save(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    text = (message.text or "").strip()
    if not text:
        await message.answer("Название кнопки пустое. Отправь непустое название.")
        return

    # Сохраняем название кнопки в состояние и переходим к следующему шагу
    await state.update_data(button_text=text)
    await state.set_state(AdminStates.waiting_for_new_button_message)
    await message.answer(
        f"Название кнопки: <b>{text}</b>\n\n"
        "Теперь отправь текст, который будет показываться при нажатии на эту кнопку:"
    )


@admin_router.message(AdminStates.waiting_for_new_button_message, F.text)
async def admin_add_button_message_save(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    message_text = (message.text or "").strip()
    if not message_text:
        await message.answer("Текст пустой. Отправь непустой текст для сообщения.")
        return

    data = await state.get_data()
    button_text = data.get("button_text")
    
    if not button_text:
        await message.answer("Ошибка: не найден текст кнопки.")
        await state.clear()
        return

    data = await state.get_data()
    parent_id = data.get("parent_id")
    
    try:
        button_id = await add_button_to_db(button_text, message_text, parent_id)
        await state.clear()

        if parent_id:
            # Если кнопка добавлена внутрь другой, возвращаемся к родителю
            from src.bot.database.buttons import get_button_by_id, get_all_buttons as get_child_buttons
            
            parent_button = await get_button_by_id(parent_id)
            if parent_button:
                # Показываем сообщение
                await message.answer(f"✅ Кнопка <b>{button_text}</b> добавлена внутрь кнопки <b>{parent_button['text']}</b>.")
                
                # Показываем родительскую кнопку с обновлёнными дочерними
                from src.bot.database.start_message import get_start_message
                parent_message_text = parent_button.get("message_text") or await get_start_message()
                
                child_buttons = await get_child_buttons(parent_id=parent_id)
                inline_keyboard = []
                
                # Добавляем дочерние кнопки (каждая в отдельный ряд - столбик)
                if child_buttons:
                    for btn in child_buttons:
                        inline_keyboard.append([
                            InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"])
                        ])
                
                inline_keyboard.append([InlineKeyboardButton(text="➕ Добавить кнопку", callback_data=f"admin_add_button_{parent_id}")])
                inline_keyboard.append([InlineKeyboardButton(text="✏️ Изменить текст кнопки", callback_data=f"edit_button_name_{parent_id}")])
                inline_keyboard.append([InlineKeyboardButton(text="✏️ Изменить текст сообщения", callback_data=f"edit_button_message_{parent_id}")])
                inline_keyboard.append([InlineKeyboardButton(text="🗑️ Удалить кнопку", callback_data=f"delete_button_{parent_id}")])
                
                if parent_button.get("parent_id"):
                    parent_parent = await get_button_by_id(parent_button["parent_id"])
                    if parent_parent:
                        inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data=parent_parent["callback_data"])])
                else:
                    inline_keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
                
                kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
                await message.answer(parent_message_text, reply_markup=kb)
                return
        
        buttons = await get_all_buttons()
        preview = "\n".join(f"- {b['text']} (ID: {b['id']})" for b in buttons) if buttons else "пока нет кнопок"

        admin_kb = await build_admin_inline_keyboard_with_user_buttons()
        await message.answer(
            f"✅ Кнопка добавлена (ID: {button_id}).\n"
            "Текущий набор ваших сконструированных кнопок:\n"
            f"{preview}",
            reply_markup=admin_kb,
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка при добавлении кнопки: {e}")
        await state.clear()


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
    await callback.message.answer(
        f"Текущее стартовое сообщение:\n\n<b>{current_text}</b>\n\n"
        "Отправь новый текст для стартового сообщения:"
    )




@admin_router.message(AdminStates.waiting_for_new_start_message, F.text)
async def admin_edit_start_message_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового стартового сообщения."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Текст пустой. Отправь непустой текст.")
        return

    try:
        from src.bot.database.start_message import update_start_message
        success = await update_start_message(new_text)
        await state.clear()

        if success:
            admin_kb = await build_admin_inline_keyboard_with_user_buttons()
            await message.answer(
                "✅ Стартовое сообщение успешно изменено.",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Не удалось обновить стартовое сообщение.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении стартового сообщения: {e}")
        await state.clear()


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
        await state.clear()


@admin_router.callback_query(F.data == "cancel_edit_text")
async def admin_edit_text_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    await state.clear()
    await callback.answer("Отменено")
    admin_kb = await build_admin_inline_keyboard_with_user_buttons()
    await callback.message.answer(
        "Изменение текста отменено.",
        reply_markup=admin_kb
    )


@admin_router.message(AdminStates.waiting_for_new_text_for_button, F.text)
async def admin_edit_text_save(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("Ошибка: не найден ID кнопки.")
        await state.clear()
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Текст пустой. Отправь непустой текст.")
        return

    try:
        success = await update_button_text(button_id, new_text)
        await state.clear()

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
        await state.clear()


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

    await state.update_data(button_id=button_id)
    await state.set_state(AdminStates.waiting_for_new_button_name)
    await callback.answer()
    await callback.message.answer(
        f"Текущее название кнопки: <b>{button['text']}</b>\n"
        "Отправь новое название кнопки:"
    )


@admin_router.message(AdminStates.waiting_for_new_button_name, F.text)
async def edit_button_name_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового названия кнопки."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("Ошибка: не найден ID кнопки.")
        await state.clear()
        return

    new_text = (message.text or "").strip()
    if not new_text:
        await message.answer("Название пустое. Отправь непустое название.")
        return

    try:
        success = await update_button_text(button_id, new_text)
        await state.clear()

        if success:
            admin_kb = await build_admin_inline_keyboard_with_user_buttons()
            await message.answer(
                f"✅ Название кнопки успешно изменено на: <b>{new_text}</b>",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Кнопка не найдена или не удалось обновить.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении названия: {e}")
        await state.clear()


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

    await state.update_data(button_id=button_id)
    await state.set_state(AdminStates.waiting_for_new_message_text)
    await callback.answer()
    
    current_message = button.get("message_text") or "не задан"
    await callback.message.answer(
        f"Текущий текст сообщения: <b>{current_message}</b>\n"
        "Отправь новый текст сообщения:"
    )


@admin_router.message(AdminStates.waiting_for_new_message_text, F.text)
async def edit_button_message_save(message: Message, state: FSMContext) -> None:
    """Сохранение нового текста сообщения кнопки."""
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    button_id = data.get("button_id")
    
    if not button_id:
        await message.answer("Ошибка: не найден ID кнопки.")
        await state.clear()
        return

    new_message_text = (message.text or "").strip()
    if not new_message_text:
        await message.answer("Текст пустой. Отправь непустой текст.")
        return

    try:
        success = await update_button_message_text(button_id, new_message_text)
        await state.clear()

        if success:
            admin_kb = await build_admin_inline_keyboard_with_user_buttons()
            await message.answer(
                f"✅ Текст сообщения успешно изменён.",
                reply_markup=admin_kb
            )
        else:
            await message.answer("❌ Кнопка не найдена или не удалось обновить.")
    except Exception as e:
        await message.answer(f"❌ Ошибка при изменении текста сообщения: {e}")
        await state.clear()


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


