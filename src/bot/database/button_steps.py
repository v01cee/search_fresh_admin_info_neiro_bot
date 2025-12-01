from typing import List, Optional, Dict
import asyncpg

from src.bot.database.db import get_db_pool


async def add_button_step(
    button_id: int,
    step_number: int,
    content_type: str,
    content_text: Optional[str] = None,
    file_id: Optional[str] = None,
    file_type: Optional[str] = None,
    delay: int = 0
) -> int:
    """Добавить шаг к кнопке. Возвращает ID созданного шага."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO button_steps (button_id, step_number, content_type, content_text, file_id, file_type, delay)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            button_id,
            step_number,
            content_type,
            content_text,
            file_id,
            file_type,
            delay
        )
        return row["id"]


async def cleanup_duplicate_steps(button_id: int) -> None:
    """Удалить дубликаты шагов для кнопки, оставляя только самый старый шаг для каждого step_number."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Удаляем все дубликаты, оставляя только шаг с минимальным id для каждого step_number
        await conn.execute(
            """
            DELETE FROM button_steps
            WHERE button_id = $1
            AND id NOT IN (
                SELECT MIN(id)
                FROM button_steps
                WHERE button_id = $1
                GROUP BY step_number
            )
            """,
            button_id
        )


async def get_button_steps(button_id: int) -> List[dict]:
    """Получить все шаги кнопки, отсортированные по номеру шага.
    Автоматически очищает дубликаты перед возвратом."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Сначала очищаем дубликаты в той же транзакции
        await conn.execute(
            """
            DELETE FROM button_steps
            WHERE button_id = $1
            AND id NOT IN (
                SELECT MIN(id)
                FROM button_steps
                WHERE button_id = $1
                GROUP BY step_number
            )
            """,
            button_id
        )
        
        # Теперь получаем шаги
        rows = await conn.fetch(
            """
            SELECT id, button_id, step_number, content_type, content_text, file_id, file_type, delay
            FROM button_steps
            WHERE button_id = $1
            ORDER BY step_number
            """,
            button_id
        )
        return [dict(row) for row in rows]


async def get_all_steps_for_buttons(button_ids: List[int]) -> Dict[int, List[dict]]:
    """Получить все шаги для списка кнопок одним запросом.
    Возвращает словарь {button_id: [список шагов]}."""
    if not button_ids:
        return {}
    
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Получаем все шаги для всех кнопок одним запросом
        rows = await conn.fetch(
            """
            SELECT id, button_id, step_number, content_type, content_text, file_id, file_type, delay
            FROM button_steps
            WHERE button_id = ANY($1::int[])
            ORDER BY button_id, step_number
            """,
            button_ids
        )
        
        # Группируем шаги по button_id
        steps_by_button = {}
        for row in rows:
            button_id = row["button_id"]
            if button_id not in steps_by_button:
                steps_by_button[button_id] = []
            steps_by_button[button_id].append(dict(row))
        
        return steps_by_button


async def delete_button_steps(button_id: int) -> bool:
    """Удалить все шаги кнопки."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM button_steps WHERE button_id = $1",
            button_id
        )
        return result.startswith("DELETE")


async def insert_step_at_position(
    button_id: int,
    position: int,
    content_type: str,
    content_text: Optional[str] = None,
    file_id: Optional[str] = None,
    file_type: Optional[str] = None,
    delay: int = 0
) -> int:
    """Вставить шаг на указанную позицию. Все шаги с номерами >= position сдвигаются вниз."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Сначала сдвигаем все шаги с номерами >= position вниз (увеличиваем номер на 1)
        await conn.execute(
            """
            UPDATE button_steps 
            SET step_number = step_number + 1 
            WHERE button_id = $1 AND step_number >= $2
            """,
            button_id,
            position
        )
        
        # Теперь вставляем новый шаг на позицию position
        row = await conn.fetchrow(
            """
            INSERT INTO button_steps (button_id, step_number, content_type, content_text, file_id, file_type, delay)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            button_id,
            position,
            content_type,
            content_text,
            file_id,
            file_type,
            delay
        )
        return row["id"]


async def get_button_step(button_id: int, step_number: int) -> Optional[dict]:
    """Получить конкретный шаг кнопки. Если есть дубликаты, возвращает первый (самый старый по id)."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Используем ORDER BY id LIMIT 1, чтобы гарантировать возврат только одного шага
        # даже если есть дубликаты (что не должно быть, но может случиться из-за ошибок)
        row = await conn.fetchrow(
            """
            SELECT id, button_id, step_number, content_type, content_text, file_id, file_type, delay
            FROM button_steps
            WHERE button_id = $1 AND step_number = $2
            ORDER BY id
            LIMIT 1
            """,
            button_id,
            step_number
        )
        return dict(row) if row else None


async def delete_button_step(button_id: int, step_number: int) -> bool:
    """Удалить конкретный шаг кнопки и обновить номера последующих шагов.
    Удаляет все дубликаты шага с данным step_number (если есть)."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        # Удаляем все шаги с данным step_number (включая дубликаты, если есть)
        result = await conn.execute(
            "DELETE FROM button_steps WHERE button_id = $1 AND step_number = $2",
            button_id,
            step_number
        )
        
        if not result.startswith("DELETE"):
            return False
        
        # Обновляем номера последующих шагов (уменьшаем на 1)
        await conn.execute(
            """
            UPDATE button_steps 
            SET step_number = step_number - 1 
            WHERE button_id = $1 AND step_number > $2
            """,
            button_id,
            step_number
        )
        
        return True


async def update_step_delay(button_id: int, step_number: int, delay: int) -> bool:
    """Обновить задержку шага."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE button_steps SET delay = $1 WHERE button_id = $2 AND step_number = $3",
            delay,
            button_id,
            step_number
        )
        return result == "UPDATE 1"


async def update_step_content(button_id: int, step_number: int, content_text: Optional[str] = None, file_id: Optional[str] = None, file_type: Optional[str] = None) -> bool:
    """Обновить содержимое шага."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        updates = []
        params = []
        param_num = 1
        
        # Определяем content_type на основе того, что обновляется
        if file_id is not None and file_id != "":
            # Если обновляется файл (и это не пустая строка), устанавливаем content_type = "file"
            updates.append(f"content_type = ${param_num}")
            params.append("file")
            param_num += 1
        elif content_text is not None:
            # Если обновляется только текст, устанавливаем content_type = "text"
            updates.append(f"content_type = ${param_num}")
            params.append("text")
            param_num += 1
        
        if content_text is not None:
            updates.append(f"content_text = ${param_num}")
            params.append(content_text)
            param_num += 1
        
        if file_id is not None:
            if file_id == "":
                # Если пустая строка, удаляем файл (устанавливаем NULL)
                updates.append("file_id = NULL")
            else:
                updates.append(f"file_id = ${param_num}")
                params.append(file_id)
                param_num += 1
        
        if file_type is not None:
            if file_type == "":
                # Если пустая строка, удаляем тип файла (устанавливаем NULL)
                updates.append("file_type = NULL")
            else:
                updates.append(f"file_type = ${param_num}")
                params.append(file_type)
                param_num += 1
        
        if not updates:
            return False
        
        params.extend([button_id, step_number])
        # Формируем правильный запрос с учетом NULL значений
        set_clause = ", ".join(updates)
        query = f"UPDATE button_steps SET {set_clause} WHERE button_id = ${param_num} AND step_number = ${param_num + 1}"
        
        result = await conn.execute(query, *params)
        return result == "UPDATE 1"

