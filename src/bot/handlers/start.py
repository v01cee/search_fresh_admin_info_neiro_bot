from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.bot.services.menu_constructor import build_user_inline_keyboard
from src.bot.database.start_message import get_start_message

start_router = Router(name="start")


@start_router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    kb = await build_user_inline_keyboard()
    start_text = await get_start_message()

    await message.answer(start_text, reply_markup=kb)


