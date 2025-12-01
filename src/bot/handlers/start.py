from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
import logging

from src.bot.services.menu_constructor import build_user_inline_keyboard
from src.bot.database.start_message import get_start_message
from src.bot.config import get_config

logger = logging.getLogger(__name__)

start_router = Router(name="start")


class FeedbackStates(StatesGroup):
    """Состояния для обратной связи."""
    waiting_for_feedback_message = State()  # Ожидание сообщения от пользователя


def _is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом."""
    config = get_config()
    return user_id in config.admin_ids


@start_router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    is_admin_user = _is_admin(user_id)
    
    # Получаем текущий стейт для отладки
    data = await state.get_data()
    current_admin_mode = data.get("admin_mode", False)
    current_user_mode = data.get("user_mode", False)
    
    logger.info(
        f"[START] user_id={user_id}, is_admin={is_admin_user}, "
        f"current_state: admin_mode={current_admin_mode}, user_mode={current_user_mode}"
    )
    
    # При команде /start ВСЕГДА устанавливаем режим пользователя
    # Админское меню доступно только через команду /admin
    await state.update_data(user_mode=True, admin_mode=False)
    logger.info(f"[START] Установлен режим пользователя для user_id={user_id} (is_admin={is_admin_user})")
    
    # Проверяем стейт после установки для отладки
    data_after = await state.get_data()
    logger.info(
        f"[START] После установки стейта: admin_mode={data_after.get('admin_mode', False)}, "
        f"user_mode={data_after.get('user_mode', False)}"
    )
    
    kb = await build_user_inline_keyboard()
    start_text = await get_start_message()

    # Отправляем стартовое сообщение и сохраняем его message_id в состоянии
    sent_message = await message.answer(start_text, reply_markup=kb)
    await state.update_data(main_menu_message_id=sent_message.message_id)


@start_router.message(FeedbackStates.waiting_for_feedback_message, F.text)
async def process_feedback(message: Message, state: FSMContext) -> None:
    """Обрабатывает сообщение обратной связи от пользователя."""
    user_id = message.from_user.id
    feedback_text = message.text
    
    logger.info(f"[FEEDBACK] Получено сообщение от пользователя {user_id}: {feedback_text}")
    
    # Здесь можно сохранить feedback в базу данных или отправить админам
    # Пока просто подтверждаем получение
    config = get_config()
    
    # Отправляем подтверждение пользователю
    back_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="<- Назад", callback_data="back_to_menu")]]
    )
    
    await message.answer(
        "Спасибо за ваше сообщение! Мы получили вашу обратную связь и обязательно её рассмотрим.",
        reply_markup=back_button
    )
    
    # Отправляем feedback админам (если нужно)
    if config.admin_ids:
        feedback_message = (
            f"📩 Новая обратная связь от пользователя:\n\n"
            f"ID: {user_id}\n"
            f"Username: @{message.from_user.username or 'не указан'}\n"
            f"Имя: {message.from_user.first_name or 'не указано'}\n\n"
            f"Сообщение:\n{feedback_text}"
        )
        
        for admin_id in config.admin_ids:
            try:
                await message.bot.send_message(chat_id=admin_id, text=feedback_message)
            except Exception as e:
                logger.error(f"[FEEDBACK] Не удалось отправить feedback админу {admin_id}: {e}")
    
    # Сбрасываем состояние
    await state.clear()

