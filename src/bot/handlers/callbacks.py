from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.bot.config import get_config
from src.bot.database.buttons import get_all_buttons, get_button_by_callback_data, get_button_by_id
from src.bot.database.start_message import get_start_message
from src.bot.services.menu_constructor import build_user_inline_keyboard, build_admin_inline_keyboard_with_user_buttons

callback_router = Router(name="callbacks")


def _is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


@callback_router.callback_query(F.data.startswith("btn_"))
async def handle_button_callback(callback: CallbackQuery) -> None:
    """Обработчик нажатий на инлайн-кнопки."""
    callback_data = callback.data

    # Получаем информацию о кнопке из БД
    button = await get_button_by_callback_data(callback_data)

    if button:
        await callback.answer(f"Вы нажали: {button['text']}")
        
        # Показываем сохранённый текст сообщения или стартовое сообщение из БД
        message_text = button.get("message_text")
        if not message_text:
            # Если текст сообщения не задан, показываем стартовое сообщение из БД
            message_text = await get_start_message()
        
        # Получаем дочерние кнопки
        child_buttons = await get_all_buttons(parent_id=button['id'])
        
        # Создаём клавиатуру с кнопками
        inline_keyboard = []
        
        # Добавляем дочерние кнопки, если они есть (каждая в отдельный ряд - столбик)
        if child_buttons:
            for btn in child_buttons:
                inline_keyboard.append([
                    InlineKeyboardButton(
                        text=btn["text"],
                        callback_data=btn["callback_data"]
                    )
                ])
        
        # Если админ - добавляем кнопки редактирования
        if _is_admin(callback.from_user.id):
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
        await callback.message.answer(message_text, reply_markup=kb)
    else:
        await callback.answer("Кнопка не найдена", show_alert=True)


@callback_router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery) -> None:
    """Возврат в главное меню."""
    start_message = await get_start_message()
    
    # Для всех (включая админов) показываем только пользовательские кнопки
    kb = await build_user_inline_keyboard()
    
    await callback.answer()
    await callback.message.answer(start_message, reply_markup=kb)

