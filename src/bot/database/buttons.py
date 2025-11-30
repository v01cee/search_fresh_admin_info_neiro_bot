from typing import List, Optional
import asyncpg

from src.bot.database.db import get_db_pool


async def add_button_to_db(text: str, message_text: str, parent_id: Optional[int] = None, delay: int = 0) -> int:
    """Добавить новую кнопку в БД. Возвращает ID созданной кнопки."""
    pool = get_db_pool()
    
    async with pool.acquire() as conn:
        # Проверяем, нет ли уже такой кнопки с таким же parent_id
        existing = await conn.fetchrow(
            "SELECT id FROM buttons WHERE text = $1 AND (parent_id = $2 OR (parent_id IS NULL AND $2 IS NULL))",
            text,
            parent_id
        )
        if existing:
            return existing["id"]
        
        # Сначала создаем кнопку с временным callback_data
        # Используем ID для создания короткого callback_data после создания
        temp_callback = "btn_temp"
        
        row = await conn.fetchrow(
            "INSERT INTO buttons (text, callback_data, message_text, parent_id, delay) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            text,
            temp_callback,
            message_text,
            parent_id,
            delay
        )
        button_id = row["id"]
        
        # Теперь создаем короткий callback_data на основе ID
        # Используем формат btn_id_123, который всегда короткий
        callback_data = f"btn_id_{button_id}"
        
        # Обновляем callback_data на основе ID
        await conn.execute(
            "UPDATE buttons SET callback_data = $1 WHERE id = $2",
            callback_data,
            button_id
        )
        
        return button_id


def _ensure_short_callback_data(callback_data: str, button_id: int) -> str:
    """Обеспечивает, что callback_data короткий. Если нет - создает на основе ID."""
    MAX_CALLBACK_DATA_LENGTH = 64
    
    if not callback_data:
        return f"btn_id_{button_id}"
    
    # Если уже в формате btn_id_XXX, возвращаем как есть
    if callback_data.startswith("btn_id_"):
        return callback_data
    
    # Проверяем длину
    byte_length = len(callback_data.encode('utf-8'))
    if byte_length <= MAX_CALLBACK_DATA_LENGTH:
        return callback_data
    
    # Если слишком длинный, создаем на основе ID
    return f"btn_id_{button_id}"


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
        
        buttons = []
        for row in rows:
            button_dict = dict(row)
            # Обеспечиваем, что callback_data короткий
            original_callback = button_dict["callback_data"]
            short_callback = _ensure_short_callback_data(original_callback, button_dict["id"])
            
            # Если callback_data был изменен, обновляем в базе
            if short_callback != original_callback:
                await conn.execute(
                    "UPDATE buttons SET callback_data = $1 WHERE id = $2",
                    short_callback,
                    button_dict["id"]
                )
                button_dict["callback_data"] = short_callback
            
            buttons.append(button_dict)
        
        return buttons


async def get_button_by_id(button_id: int) -> Optional[dict]:
    """Получить кнопку по ID."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE id = $1",
            button_id
        )
        if not row:
            return None
        
        button_dict = dict(row)
        # Обеспечиваем, что callback_data короткий
        original_callback = button_dict["callback_data"]
        short_callback = _ensure_short_callback_data(original_callback, button_id)
        
        # Если callback_data был изменен, обновляем в базе
        if short_callback != original_callback:
            await conn.execute(
                "UPDATE buttons SET callback_data = $1 WHERE id = $2",
                short_callback,
                button_id
            )
            button_dict["callback_data"] = short_callback
        
        return button_dict


async def get_button_by_callback_data(callback_data: str) -> Optional[dict]:
    """Получить кнопку по callback_data."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Сначала пытаемся найти по точному совпадению
        row = await conn.fetchrow(
            "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE callback_data = $1",
            callback_data
        )
        
        # Если не найдено и callback_data в формате btn_id_XXX, извлекаем ID
        if not row and callback_data.startswith("btn_id_"):
            try:
                button_id = int(callback_data.replace("btn_id_", ""))
                row = await conn.fetchrow(
                    "SELECT id, text, callback_data, message_text, parent_id, file_id, file_type, delay FROM buttons WHERE id = $1",
                    button_id
                )
            except (ValueError, AttributeError):
                pass
        
        if not row:
            return None
        
        button_dict = dict(row)
        # Обеспечиваем, что callback_data короткий
        original_callback = button_dict["callback_data"]
        short_callback = _ensure_short_callback_data(original_callback, button_dict["id"])
        
        # Если callback_data был изменен, обновляем в базе
        if short_callback != original_callback:
            await conn.execute(
                "UPDATE buttons SET callback_data = $1 WHERE id = $2",
                short_callback,
                button_dict["id"]
            )
            button_dict["callback_data"] = short_callback
        
        return button_dict


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
    """Исправляет все callback_data, пересоздавая их на основе ID кнопок."""
    import logging
    logger = logging.getLogger(__name__)
    
    MAX_CALLBACK_DATA_LENGTH = 64
    
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Получаем все кнопки
        rows = await conn.fetch("SELECT id, callback_data FROM buttons")
        logger.info(f"Проверка callback_data: найдено {len(rows)} кнопок")
        
        # Фильтруем кнопки, которые нужно исправить
        # Исправляем все кнопки, у которых callback_data не начинается с btn_id_ или превышает 64 байта
        to_fix = []
        for row in rows:
            callback_data = row["callback_data"]
            if not callback_data:
                to_fix.append(row)
            elif not callback_data.startswith("btn_id_"):
                # Если callback_data не на основе ID, исправляем
                to_fix.append(row)
            elif len(callback_data.encode('utf-8')) > MAX_CALLBACK_DATA_LENGTH:
                # Если даже btn_id_XXX слишком длинный (маловероятно, но на всякий случай)
                to_fix.append(row)
        
        logger.info(f"Найдено {len(to_fix)} кнопок для исправления")
        
        fixed_count = 0
        for row in to_fix:
            button_id = row["id"]
            old_callback = row["callback_data"]
            
            # Создаем новый callback_data на основе ID
            new_callback = f"btn_id_{button_id}"
            
            # Проверяем, что новый callback_data не превышает лимит (маловероятно для btn_id_XXX)
            if len(new_callback.encode('utf-8')) > MAX_CALLBACK_DATA_LENGTH:
                # Если ID слишком большой, используем хеш
                import hashlib
                hash_suffix = hashlib.md5(str(button_id).encode('utf-8')).hexdigest()[:16]
                new_callback = f"btn_{hash_suffix}"
            
            # Обновляем callback_data
            await conn.execute(
                "UPDATE buttons SET callback_data = $1 WHERE id = $2",
                new_callback,
                button_id
            )
            fixed_count += 1
            if old_callback:
                old_len = len(old_callback.encode('utf-8'))
                new_len = len(new_callback.encode('utf-8'))
                logger.info(f"Исправлен callback_data для кнопки ID={button_id}: {old_len} -> {new_len} байт")
            else:
                logger.info(f"Создан callback_data для кнопки ID={button_id}: {len(new_callback.encode('utf-8'))} байт")
        
        logger.info(f"Исправлено {fixed_count} кнопок")

