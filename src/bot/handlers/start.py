from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import logging

from src.bot.services.menu_constructor import build_user_inline_keyboard
from src.bot.database.start_message import get_start_message
from src.bot.config import get_config

logger = logging.getLogger(__name__)

start_router = Router(name="start")


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


@start_router.message(Command("group_id"))
async def cmd_group_id(message: Message) -> None:
    """
    Команда для получения ID текущего чата (группы/супергруппы/канала или личного чата).
    Удобно кидать в нужную группу и вызывать /group_id.
    """
    chat = message.chat
    await message.answer(
        "Информация о чате:\n"
        f"ID: <code>{chat.id}</code>\n"
        f"Тип: <code>{chat.type}</code>\n"
        f"Название: <code>{chat.title or '—'}</code>"
    )


