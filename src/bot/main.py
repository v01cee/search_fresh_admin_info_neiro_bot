import logging
import atexit

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from .config import get_config
from .database import init_db, close_db
from .handlers.start import start_router
from .handlers.admin import admin_router
from .handlers.callbacks import callback_router
from .handlers.search import search_router
from .handlers.echo import echo_router


async def main() -> None:
    config = get_config()

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Инициализация БД
    await init_db()
    logging.info("База данных подключена.")

    # Регистрация обработчика закрытия БД
    atexit.register(lambda: __import__("asyncio").run(close_db()))

    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров
    dp.include_router(start_router)
    dp.include_router(admin_router)
    dp.include_router(search_router)
    dp.include_router(callback_router)
    dp.include_router(echo_router)  # Показывает ID пользователя, если он пишет вне контекста

    logging.info("Бот запущен. Нажми Ctrl+C для остановки.")

    try:
        await dp.start_polling(bot)
    finally:
        await close_db()


