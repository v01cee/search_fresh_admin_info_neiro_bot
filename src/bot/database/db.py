import asyncpg
from typing import Optional

from src.bot.config import get_config

_pool: Optional[asyncpg.Pool] = None


async def init_db() -> None:
    """Инициализация подключения к БД и создание таблиц."""
    global _pool
    config = get_config()

    _pool = await asyncpg.create_pool(
        host=config.db_host,
        port=config.db_port,
        database=config.db_name,
        user=config.db_user,
        password=config.db_password,
        min_size=1,
        max_size=10,
    )

    # Создаём таблицу для кнопок, если её нет
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS buttons (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                callback_data TEXT NOT NULL UNIQUE,
                message_text TEXT,
                parent_id INTEGER REFERENCES buttons(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Создаём таблицу для стартового сообщения
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS start_message (
                id INTEGER PRIMARY KEY DEFAULT 1,
                text TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT single_row CHECK (id = 1)
            )
        """)
        # Инициализируем стартовое сообщение, если его нет
        existing = await conn.fetchrow("SELECT id FROM start_message WHERE id = 1")
        if not existing:
            default_text = (
                "Руководитель отдела оценки и Руководитель отдела продаж\n"
                "компании FRESH  это лидеры команды профессионалов!\n\n"
                "✊Играющий тренер\n"
                "✊Лучший специалист\n"
                "✊Эксперт по продукту\n"
                "✊Наставник\n"
                "✊Искатель кадров\n"
                "✊Психолог и мотиватор\n\n"
                "Но даже сильному лидеру и профессионалу, порой\n"
                "нужна поддержка!\n"
                "Поэтому мы создали этого FRESHBOTа, который\n"
                "поможет тебе в повседневной работе с командой,\n"
                "целями и процессами! 😉"
            )
            await conn.execute(
                "INSERT INTO start_message (id, text) VALUES (1, $1)",
                default_text
            )
        # Добавляем колонки, если их нет (для существующих БД)
        try:
            await conn.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS message_text TEXT")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS parent_id INTEGER REFERENCES buttons(id) ON DELETE CASCADE")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS file_id TEXT")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS file_type TEXT")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE buttons ADD COLUMN IF NOT EXISTS delay INTEGER DEFAULT 0")
        except Exception:
            pass
        # Создаём таблицу для шагов кнопки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS button_steps (
                id SERIAL PRIMARY KEY,
                button_id INTEGER NOT NULL REFERENCES buttons(id) ON DELETE CASCADE,
                step_number INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content_text TEXT,
                file_id TEXT,
                file_type TEXT,
                delay INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(button_id, step_number)
            )
        """)


async def close_db() -> None:
    """Закрытие подключения к БД."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_db_pool() -> asyncpg.Pool:
    """Получить пул подключений к БД."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_db() first.")
    return _pool

