from typing import List, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.bot.database.buttons import get_all_buttons


async def build_user_inline_keyboard() -> Optional[InlineKeyboardMarkup]:
    """
    Построить инлайн-клавиатуру для обычных пользователей
    на основе кнопок из БД.
    """
    buttons = await get_all_buttons()

    # Создаём инлайн-кнопки: каждая кнопка в отдельный ряд (столбик)
    inline_buttons = []
    
    # Добавляем пользовательские кнопки
    if buttons:
        for btn in buttons:
            inline_buttons.append([
                InlineKeyboardButton(
                    text=btn["text"],
                    callback_data=btn["callback_data"]
                )
            ])
    
    # Добавляем кнопку поиска в конце
    inline_buttons.append([
        InlineKeyboardButton(text="🔍 Поиск", callback_data="start_search")
    ])

    return InlineKeyboardMarkup(inline_keyboard=inline_buttons)


async def build_admin_inline_keyboard_with_user_buttons() -> InlineKeyboardMarkup:
    """
    Построить инлайн-клавиатуру для админа:
    сначала пользовательские кнопки (из БД), потом админские.
    """
    from src.bot.keyboards.common import admin_inline_keyboard
    
    # Получаем пользовательские кнопки
    user_buttons = await get_all_buttons()
    
    # Получаем админскую клавиатуру
    admin_kb = admin_inline_keyboard()
    
    # Объединяем: сначала пользовательские, потом админские
    inline_keyboard = []
    
    # Добавляем пользовательские кнопки (каждая в отдельный ряд - столбик)
    if user_buttons:
        for btn in user_buttons:
            inline_keyboard.append([
                InlineKeyboardButton(
                    text=btn["text"],
                    callback_data=btn["callback_data"]
                )
            ])
    
    # Добавляем админские кнопки
    inline_keyboard.extend(admin_kb.inline_keyboard)
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def get_all_buttons_list() -> List[dict]:
    """Получить список всех кнопок из БД."""
    return await get_all_buttons()
