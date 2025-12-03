from typing import List, Optional

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.bot.database.buttons import get_all_buttons

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
            # Формируем текст кнопки с галочкой и задержкой, если есть
            button_text = btn["text"]
            delay = btn.get("delay", 0)
            if delay and delay > 0:
                button_text = f"{button_text} ✓ ({delay} сек)"
            
            inline_buttons.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=_truncate_callback_data(btn["callback_data"])
                )
            ])
    
    # Возвращаем клавиатуру только с пользовательскими кнопками
    if not inline_buttons:
        return None
    
    return InlineKeyboardMarkup(inline_keyboard=inline_buttons)


async def build_user_main_menu_keyboard() -> Optional[InlineKeyboardMarkup]:
    """
    Построить главное меню для пользователя:
    - все пользовательские кнопки из БД
    - отдельная кнопка 'Обратная связь' внизу.
    """
    base_kb = await build_user_inline_keyboard()
    inline_keyboard = base_kb.inline_keyboard if base_kb else []

    # Добавляем кнопку "Обратная связь" всегда в самый низ
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="Обратная связь",
                callback_data="feedback_start",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


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
            # Формируем текст кнопки с галочкой и задержкой, если есть
            button_text = btn["text"]
            delay = btn.get("delay", 0)
            if delay and delay > 0:
                button_text = f"{button_text} ✓ ({delay} сек)"
            
            inline_keyboard.append([
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=btn["callback_data"]
                )
            ])
    
    # Добавляем админские кнопки
    inline_keyboard.extend(admin_kb.inline_keyboard)
    
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


async def get_all_buttons_list() -> List[dict]:
    """Получить список всех кнопок из БД."""
    return await get_all_buttons()
