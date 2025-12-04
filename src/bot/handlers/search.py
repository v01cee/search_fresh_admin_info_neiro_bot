from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.bot.config import get_config
from src.bot.services.menu_constructor import build_user_inline_keyboard
from src.bot.services.ai_search import ai_search_buttons

search_router = Router(name="search")


class SearchStates(StatesGroup):
    waiting_for_search_query = State()


def _is_admin(user_id: int) -> bool:
    config = get_config()
    return user_id in config.admin_ids


def _is_feedback_chat(chat_id: int) -> bool:
    """
    Возвращает True, если сообщение пришло в чат, который используется как
    группа для обратной связи. В таком чате поиск работать не должен.
    """
    config = get_config()
    return bool(config.feedback_chat_id) and chat_id == config.feedback_chat_id


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


async def _clear_state_preserving_admin(state: FSMContext, user_id: int) -> None:
    """Очищает состояние, сохраняя текущий режим пользователя (user_mode/admin_mode)."""
    # Сохраняем текущий режим перед очисткой
    data = await state.get_data()
    saved_admin_mode = data.get("admin_mode", False)
    saved_user_mode = data.get("user_mode", False)
    
    # Очищаем состояние
    await state.clear()
    
    # Восстанавливаем сохраненный режим
    await state.update_data(admin_mode=saved_admin_mode, user_mode=saved_user_mode)


@search_router.message(Command("search"))
async def search_start_command(message: Message, state: FSMContext) -> None:
    """Начало поиска через команду."""
    # Не запускаем поиск в чате обратной связи
    if _is_feedback_chat(message.chat.id):
        return
    await state.set_state(SearchStates.waiting_for_search_query)
    await message.answer("🔍 Введи текст для поиска:")


@search_router.callback_query(F.data == "start_search")
async def search_start_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало поиска через кнопку в стартовом меню."""
    # Не запускаем поиск в чате обратной связи
    if _is_feedback_chat(callback.message.chat.id):
        await callback.answer()
        return
    await state.set_state(SearchStates.waiting_for_search_query)
    await callback.answer()
    await callback.message.answer("🔍 Введи текст для поиска:")


@search_router.message(SearchStates.waiting_for_search_query, F.text)
async def search_execute(message: Message, state: FSMContext) -> None:
    """Выполнение поиска."""
    # Не выполняем поиск в чате обратной связи
    if _is_feedback_chat(message.chat.id):
        await state.clear()
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("Поисковый запрос пустой. Введи текст для поиска.")
        return
    
    if len(query) < 2:
        await message.answer("Поисковый запрос слишком короткий. Введи минимум 2 символа.")
        return
    
    # Отправляем сообщение о начале поиска
    search_start_msg = await message.answer("🔍 Поиск начат, это может занять некоторое время...")
    
    try:
        # Всегда используем AI-поиск через DeepSeek
        error_message, results = await ai_search_buttons(query)
        
        # Удаляем сообщение о начале поиска
        try:
            await search_start_msg.delete()
        except:
            pass
        
        # Если AI вернул сообщение об ошибке (бессмысленный запрос)
        if error_message:
            # Добавляем кнопку "Назад" и НЕ очищаем состояние, чтобы пользователь мог снова отправить запрос
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]
            ])
            await message.answer(error_message, reply_markup=kb)
            # НЕ очищаем состояние - пользователь может снова отправить запрос
            return
        
        # Очищаем состояние только если поиск успешен
        await _clear_state_preserving_admin(state, message.from_user.id)
        
        # Удаляем дубликаты по названию кнопки (по запросу: одна кнопка с одинаковым названием)
        unique_results = []
        seen_titles: set[str] = set()
        for btn in results:
            title = (btn.get("text") or "").strip().lower()
            if not title:
                # Если по какой‑то причине нет названия, просто добавляем как есть
                unique_results.append(btn)
                continue
            if title in seen_titles:
                # Пропускаем дубликат с тем же названием
                continue
            seen_titles.add(title)
            unique_results.append(btn)

        # Если ничего не найдено (после удаления дубликатов)
        if not unique_results:
            await message.answer(
                f"❌ По запросу <b>«{query}»</b> ничего не найдено.\n"
                "Попробуй другой запрос или используй более общие слова."
            )
            return
        
        # Показываем результаты поиска
        results_text = f"🔍 Найдено кнопок: <b>{len(unique_results)}</b>\n\n"
        inline_keyboard = []
        
        for btn in unique_results[:10]:  # Ограничиваем до 10 результатов
            parent_info = ""
            if btn.get("parent_id"):
                from src.bot.database.buttons import get_button_by_id
                parent = await get_button_by_id(btn["parent_id"])
                if parent:
                    parent_info = f" (внутри «{parent['text']}»)"
            
            results_text += f"• <b>{btn['text']}</b>{parent_info}\n"
            inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"📌 {btn['text']}",
                    callback_data=_truncate_callback_data(btn["callback_data"])
                )
            ])
        
        if len(unique_results) > 10:
            results_text += f"\n... и ещё {len(unique_results) - 10} кнопок"
        
        # Кнопка "Назад"
        inline_keyboard.append([
            InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")
        ])
        
        kb = InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
        await message.answer(results_text, reply_markup=kb)
        
    except Exception as e:
        # Удаляем сообщение о начале поиска при ошибке
        try:
            await search_start_msg.delete()
        except:
            pass
        await message.answer(f"❌ Ошибка при поиске: {e}")
        await _clear_state_preserving_admin(state, message.from_user.id)


@search_router.message(F.text)
async def search_from_free_text(message: Message, state: FSMContext) -> None:
    """
    Запуск поиска по любому текстовому сообщению.
    Должен иметь самый низкий приоритет:
    - НЕ срабатывает, если уже есть какое-то состояние FSM (админ/поиск/редактирование).
    - НЕ срабатывает, если пользователь сейчас в чистом админ-режиме (admin_mode=True, user_mode=False).
    - Игнорирует команды (сообщения, начинающиеся с '/').
    Во всех остальных случаях просто прокидывает сообщение в стандартный search_execute.
    """
    # Не перехватываем, если уже есть активное состояние (админские стейты, поиск и т.п.)
    current_state = await state.get_state()
    if current_state:
        return
    
    # Не трогаем сообщения в "чистом" админ-режиме
    data = await state.get_data()
    admin_mode = data.get("admin_mode", False)
    user_mode = data.get("user_mode", False)
    if admin_mode and not user_mode:
        return
    
    # Не обрабатываем команды
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    # Не запускаем автопоиск в чате обратной связи
    if _is_feedback_chat(message.chat.id):
        return
    
    # Ставим состояние поиска, чтобы другие роутеры (например, echo) не срабатывали параллельно
    await state.set_state(SearchStates.waiting_for_search_query)
    await search_execute(message, state)

