from typing import List, Optional
import asyncpg

from src.bot.database.db import get_db_pool


async def add_button_to_db(text: str, message_text: str, parent_id: Optional[int] = None, delay: int = 0) -> int:
    """Добавить новую кнопку в БД. Возвращает ID созданной кнопки."""
    pool = get_db_pool()
    # Генерируем callback_data из текста (упрощённо, можно улучшить)
    # Telegram ограничивает callback_data до 64 байт
    MAX_CALLBACK_DATA_LENGTH = 64
    
    # Создаем базовый callback_data из текста
    base_callback = f"btn_{text.lower().replace(' ', '_')}"
    
    # Если есть parent_id, добавляем его к callback_data для уникальности
    if parent_id:
        base_callback = f"{base_callback}_p{parent_id}"
    
    # Обрезаем до максимальной длины, оставляя место для суффикса при необходимости
    callback_data = base_callback[:MAX_CALLBACK_DATA_LENGTH - 10]  # Оставляем место для суффикса
    
    async with pool.acquire() as conn:
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
            suffix = f"_{counter}"
            # Обрезаем callback_data, чтобы поместился суффикс
            max_base_length = MAX_CALLBACK_DATA_LENGTH - len(suffix)
            callback_data = f"{original_callback[:max_base_length]}{suffix}"
            counter += 1
            # Защита от бесконечного цикла
            if counter > 1000:
                # Если не удалось найти уникальный callback_data, используем хеш
                import hashlib
                hash_suffix = hashlib.md5(f"{text}_{parent_id}_{counter}".encode()).hexdigest()[:8]
                callback_data = f"btn_{hash_suffix}"
                break
        
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


async def fix_long_callback_data() -> None:
    """Исправляет все callback_data, которые превышают 64 байта."""
    MAX_CALLBACK_DATA_LENGTH = 64
    
    def truncate_callback_data(callback_data: str) -> str:
        """Обрезает callback_data до максимальной длины."""
        if not callback_data:
            return "btn_invalid"
        
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
    
    import logging
    logger = logging.getLogger(__name__)
    
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Получаем все кнопки и проверяем длину callback_data в байтах
        rows = await conn.fetch("SELECT id, callback_data FROM buttons")
        logger.info(f"Проверка callback_data: найдено {len(rows)} кнопок")
        
        # Фильтруем только те, у которых callback_data превышает 64 байта
        long_callbacks = []
        for row in rows:
            callback_data = row["callback_data"]
            if callback_data:
                byte_length = len(callback_data.encode('utf-8'))
                if byte_length > MAX_CALLBACK_DATA_LENGTH:
                    long_callbacks.append(row)
                    logger.warning(f"Найдена кнопка с длинным callback_data: ID={row['id']}, длина={byte_length} байт")
        
        logger.info(f"Найдено {len(long_callbacks)} кнопок с длинным callback_data")
        
        fixed_count = 0
        for row in long_callbacks:
            old_callback = row["callback_data"]
            new_callback = truncate_callback_data(old_callback)
            
            if new_callback != old_callback:
                # Проверяем, нет ли уже кнопки с таким callback_data
                existing = await conn.fetchrow(
                    "SELECT id FROM buttons WHERE callback_data = $1 AND id != $2",
                    new_callback,
                    row["id"]
                )
                
                if existing:
                    # Если уже есть, добавляем суффикс
                    counter = 1
                    while True:
                        test_callback = f"{new_callback[:MAX_CALLBACK_DATA_LENGTH - 10]}_{counter}"
                        test_callback = truncate_callback_data(test_callback)
                        existing = await conn.fetchrow(
                            "SELECT id FROM buttons WHERE callback_data = $1 AND id != $2",
                            test_callback,
                            row["id"]
                        )
                        if not existing:
                            new_callback = test_callback
                            break
                        counter += 1
                        if counter > 1000:
                            # Используем хеш
                            import hashlib
                            hash_suffix = hashlib.md5(f"{old_callback}_{row['id']}".encode('utf-8')).hexdigest()[:16]
                            new_callback = f"btn_{hash_suffix}"
                            break
                
                # Обновляем callback_data
                await conn.execute(
                    "UPDATE buttons SET callback_data = $1 WHERE id = $2",
                    new_callback,
                    row["id"]
                )
                fixed_count += 1
                logger.info(f"Исправлен callback_data для кнопки ID={row['id']}: {len(old_callback.encode('utf-8'))} -> {len(new_callback.encode('utf-8'))} байт")
        
        logger.info(f"Исправлено {fixed_count} кнопок с длинным callback_data")

