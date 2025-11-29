from typing import List, Optional
import asyncpg

from src.bot.database.db import get_db_pool


async def add_button_to_db(text: str, message_text: str, parent_id: Optional[int] = None, delay: int = 0) -> int:
    """Добавить новую кнопку в БД. Возвращает ID созданной кнопки."""
    pool = get_db_pool()
    # Генерируем callback_data из текста (упрощённо, можно улучшить)
    callback_data = f"btn_{text.lower().replace(' ', '_')[:50]}"
    
    async with pool.acquire() as conn:
        # Если есть parent_id, добавляем его к callback_data для уникальности
        if parent_id:
            callback_data = f"{callback_data}_p{parent_id}"
        
        # Проверяем, нет ли уже такой кнопки с таким же parent_id
        existing = await conn.fetchrow(
            "SELECT id FROM buttons WHERE text = $1 AND (parent_id = $2 OR (parent_id IS NULL AND $2 IS NULL))",
            text,
            parent_id
        )
        if existing:
            return existing["id"]
        
        # Если callback_data уже занят, добавляем суффикс
        counter = 1
        original_callback = callback_data
        while await conn.fetchrow("SELECT id FROM buttons WHERE callback_data = $1", callback_data):
            callback_data = f"{original_callback}_{counter}"
            counter += 1
        
        row = await conn.fetchrow(
            "INSERT INTO buttons (text, callback_data, message_text, parent_id, delay) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            text,
            callback_data,
            message_text,
            parent_id,
            delay
        )
        return row["id"]


async def get_all_buttons(parent_id: Optional[int] = None) -> List[dict]:
    """Получить все кнопки из БД. Если указан parent_id, возвращает только дочерние кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        if parent_id is not None:
            rows = await conn.fetch(
                "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE parent_id = $1 ORDER BY id",
                parent_id
            )
        else:
            rows = await conn.fetch(
                "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE parent_id IS NULL ORDER BY id"
            )
        return [dict(row) for row in rows]


async def get_button_by_id(button_id: int) -> Optional[dict]:
    """Получить кнопку по ID."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE id = $1",
            button_id
        )
        return dict(row) if row else None


async def get_button_by_callback_data(callback_data: str) -> Optional[dict]:
    """Получить кнопку по callback_data."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE callback_data = $1",
            callback_data
        )
        return dict(row) if row else None


async def update_button_text(button_id: int, new_text: str) -> bool:
    """Обновить текст кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE buttons SET text = $1 WHERE id = $2",
            new_text,
            button_id
        )
        return result == "UPDATE 1"


async def delete_button(button_id: int) -> bool:
    """Удалить кнопку."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM buttons WHERE id = $1",
            button_id
        )
        return result == "DELETE 1"


async def update_button_message_text(button_id: int, new_message_text: str) -> bool:
    """Обновить текст сообщения кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE buttons SET message_text = $1 WHERE id = $2",
            new_message_text,
            button_id
        )
        return result == "UPDATE 1"


async def search_buttons(query: str) -> List[dict]:
    """Поиск кнопок по названию и тексту сообщения."""
    pool = get_db_pool()
    search_pattern = f"%{query.lower()}%"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay 
            FROM buttons 
            WHERE LOWER(text) LIKE $1 OR LOWER(message_text) LIKE $1
            ORDER BY id
            """,
            search_pattern
        )
        return [dict(row) for row in rows]


async def update_button_file(button_id: int, file_id: str, file_type: str) -> bool:
    """Обновить файл кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE buttons SET file_id = $1, file_type = $2 WHERE id = $3",
            file_id,
            file_type,
            button_id
        )
        return result == "UPDATE 1"


async def remove_button_file(button_id: int) -> bool:
    """Удалить файл у кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE buttons SET file_id = NULL, file_type = NULL WHERE id = $1",
            button_id
        )
        return result == "UPDATE 1"


async def update_button_delay(button_id: int, delay: int) -> bool:
    """Обновить задержку кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE buttons SET delay = $1 WHERE id = $2",
            delay,
            button_id
        )
        return result == "UPDATE 1"

