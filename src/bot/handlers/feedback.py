from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.bot.config import get_config
from src.bot.database.start_message import get_start_message
from src.bot.services.menu_constructor import build_user_main_menu_keyboard


class FeedbackStates(StatesGroup):
    waiting_for_feedback = State()


feedback_router = Router(name="feedback")


@feedback_router.callback_query(F.data == "feedback_start")
async def feedback_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запуск сценария обратной связи по кнопке "Обратная связь" из главного меню.
    """
    await state.set_state(FeedbackStates.waiting_for_feedback)
    await callback.answer()
    await callback.message.answer("✍️ Сообщи, если что-то не нашел или что-то работает не так.\n\n"
                                  "Можешь отправить текст, голос, фото или документ.")


@feedback_router.message(FeedbackStates.waiting_for_feedback)
async def handle_feedback_message(message: Message, state: FSMContext) -> None:
    """
    Получает любое сообщение пользователя как обратную связь,
    отправляет его в группу из .env и возвращает пользователя в главное меню.
    """
    config = get_config()
    feedback_chat_id = config.feedback_chat_id

    user = message.from_user
    chat = message.chat

    header = (
        "📩 Новая обратная связь от пользователя:\n"
        f"👤 User ID: <code>{user.id}</code>\n"
        f"🔗 Username: @{user.username}" if user.username else "🔗 Username: —"
    )
    header += f"\n👤 Имя: {user.full_name}"
    header += f"\n💬 Chat ID: <code>{chat.id}</code>\n"
    header += f"🏷️ Chat type: <code>{chat.type}</code>\n"
    if chat.title:
        header += f"📛 Chat title: <code>{chat.title}</code>\n"

    # Пытаемся отправить в группу, но даже при ошибке благодарим пользователя
    if not feedback_chat_id:
        await message.answer("⚠️ Обратная связь временно недоступна для администраторов.")
    else:
        try:
            # Сначала отправляем заголовок с инфой о пользователе
            await message.bot.send_message(chat_id=feedback_chat_id, text=header)
            # Затем пересылаем само сообщение (любой тип контента)
            await message.forward(chat_id=feedback_chat_id)
        except Exception:
            await message.answer("⚠️ Не удалось отправить обратную связь администратору, но твоё сообщение получено.")

    # Очищаем состояние и возвращаем в главное меню
    await state.clear()

    # Благодарность пользователю
    await message.answer("Молодец, ты сделал полезное дело!")

    # Возвращаем в главное меню
    start_text = await get_start_message()
    kb = await build_user_main_menu_keyboard()
    await message.answer(start_text, reply_markup=kb)


