from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from src.bot.services.menu_constructor import build_user_inline_keyboard
from src.bot.handlers.search import SearchStates
from src.bot.handlers.admin import AdminStates
from src.bot.handlers.start import FeedbackStates

echo_router = Router(name="echo")


@echo_router.message(F.text)
async def echo_message(message: Message, state: FSMContext) -> None:
    """Показывает ID пользователя, если он пишет вне контекста поиска или админ-панели."""
    # Проверяем, не в состоянии ли пользователь поиска, админ-панели или feedback
    current_state = await state.get_state()
    
    # Если пользователь в состоянии поиска, админ-панели или feedback, не обрабатываем здесь
    # (эти состояния обрабатываются соответствующими роутерами)
    if current_state:
        state_str = str(current_state)
        if "SearchStates" in state_str or "AdminStates" in state_str or "FeedbackStates" in state_str:
            return
    
    # Показываем ID пользователя
    user_id = message.from_user.id
    username = message.from_user.username or "не указан"
    first_name = message.from_user.first_name or "не указано"
    
    kb = await build_user_inline_keyboard()
    
    await message.answer(
        f"Ваш ID: <code>{user_id}</code>\n"
        f"Username: @{username}\n"
        f"Имя: {first_name}",
        reply_markup=kb,
    )


