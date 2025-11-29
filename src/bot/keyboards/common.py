from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_inline_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-клавиатура для админ-панели."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить кнопку", callback_data="admin_add_button")],
            [InlineKeyboardButton(text="✏️ Изменить текст", callback_data="admin_edit_text")],
        ]
    )


