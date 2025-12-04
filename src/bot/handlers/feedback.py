from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton

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

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="feedback_cancel")],
        ]
    )

    await callback.message.answer(
        "✍️ Сообщи, если что-то не нашел или что-то работает не так.\n\n"
        "Можешь отправить текст, голос, фото или документ.",
        reply_markup=kb,
    )


@feedback_router.callback_query(F.data == "feedback_cancel")
async def feedback_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Отмена ввода обратной связи и возврат в главное меню.
    """
    await state.clear()
    await callback.answer()

    start_text = await get_start_message()
    kb = await build_user_main_menu_keyboard()
    await callback.message.answer(start_text, reply_markup=kb)


@feedback_router.message(FeedbackStates.waiting_for_feedback)
async def handle_feedback_message(message: Message, state: FSMContext) -> None:
    """
    Получает любое сообщение пользователя как обратную связь,
    отправляет его в группу из .env и возвращает пользователя в главное меню.
    """
    config = get_config()
    feedback_chat_id = config.feedback_chat_id

    # Пытаемся отправить в группу, но даже при ошибке благодарим пользователя
    if not feedback_chat_id:
        await message.answer("⚠️ Обратная связь временно недоступна для администраторов.")
    else:
        try:
            bot = message.bot
            # Отправляем только само сообщение пользователя (без служебных заголовков)
            if message.text:
                await bot.send_message(chat_id=feedback_chat_id, text=message.text)
            elif message.photo:
                await bot.send_photo(
                    chat_id=feedback_chat_id,
                    photo=message.photo[-1].file_id,
                    caption=message.caption or "",
                )
            elif message.document:
                await bot.send_document(
                    chat_id=feedback_chat_id,
                    document=message.document.file_id,
                    caption=message.caption or "",
                )
            elif message.video:
                await bot.send_video(
                    chat_id=feedback_chat_id,
                    video=message.video.file_id,
                    caption=message.caption or "",
                )
            elif message.voice:
                await bot.send_voice(
                    chat_id=feedback_chat_id,
                    voice=message.voice.file_id,
                    caption=message.caption or "",
                )
            elif message.audio:
                await bot.send_audio(
                    chat_id=feedback_chat_id,
                    audio=message.audio.file_id,
                    caption=message.caption or "",
                )
            elif message.video_note:
                await bot.send_video_note(
                    chat_id=feedback_chat_id,
                    video_note=message.video_note.file_id,
                )
            elif message.sticker:
                await bot.send_sticker(
                    chat_id=feedback_chat_id,
                    sticker=message.sticker.file_id,
                )
            else:
                # На всякий случай отправляем как forward, если тип контента не обработан явно
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


