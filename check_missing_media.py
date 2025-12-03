import asyncio
from typing import List, Dict, Optional

from src.bot.database.db import init_db, close_db
from src.bot.database.buttons import get_all_buttons
from src.bot.database.button_steps import get_all_steps_for_buttons


async def _get_all_buttons_recursive(parent_id: Optional[int] = None) -> List[Dict]:
    """
    Рекурсивно получить все кнопки (включая вложенные),
    сохраняя parent_id для построения путей.
    """
    buttons = await get_all_buttons(parent_id=parent_id)
    all_buttons: List[Dict] = []

    for btn in buttons:
        all_buttons.append(btn)
        children = await _get_all_buttons_recursive(parent_id=btn["id"])
        all_buttons.extend(children)

    return all_buttons


def _build_parent_paths(all_buttons: List[Dict]) -> Dict[int, str]:
    """
    Построить человекочитаемые пути до кнопок вида:
    "Родитель 1 > Родитель 2".
    """
    by_id = {b["id"]: b for b in all_buttons}
    paths: Dict[int, str] = {}

    for btn in all_buttons:
        current_id = btn["id"]
        parent_id = btn.get("parent_id")
        parts: List[str] = []

        while parent_id:
            parent = by_id.get(parent_id)
            if not parent:
                break
            parts.insert(0, parent.get("text") or f"#{parent_id}")
            parent_id = parent.get("parent_id")

        paths[current_id] = " > ".join(parts) if parts else ""

    return paths


def _has_media(file_id: Optional[str], file_type: Optional[str]) -> bool:
    """
    Проверка, является ли пара (file_id, file_type) медиа‑контентом.
    """
    if not file_id or not file_type:
        return False

    media_types = {
        "photo",
        "video",
        "document",
        "animation",
        "video_note",
        "voice",
        "audio",
        "sticker",
    }
    return file_type in media_types


async def main() -> None:
    """
    Скрипт проверки кнопок:
    - обходит все кнопки (включая вложенные)
    - смотрит файл самой кнопки и все шаги
    - выводит список кнопок, у которых НЕТ ни одного файла
      (ни у кнопки, ни в её шагах).
    """
    await init_db()
    try:
        all_buttons = await _get_all_buttons_recursive()
        if not all_buttons:
            print("Кнопок в базе не найдено.")
            return

        button_ids = [b["id"] for b in all_buttons]
        all_steps_by_button = await get_all_steps_for_buttons(button_ids)
        parent_paths = _build_parent_paths(all_buttons)

        buttons_without_media: List[Dict] = []

        for btn in all_buttons:
            btn_id = btn["id"]
            has_media = _has_media(btn.get("file_id"), btn.get("file_type"))

            # Проверяем шаги этой кнопки
            steps = all_steps_by_button.get(btn_id, [])
            if not has_media and steps:
                for step in steps:
                    if _has_media(step.get("file_id"), step.get("file_type")):
                        has_media = True
                        break

            if not has_media:
                buttons_without_media.append(btn)

        print(f"Всего кнопок (включая вложенные): {len(all_buttons)}")
        print(f"Кнопок без какого‑либо медиа (кнопка + её шаги): {len(buttons_without_media)}")
        print("-" * 60)

        for btn in buttons_without_media:
            path = parent_paths.get(btn["id"]) or ""
            full_name = btn.get("text") or f"#{btn['id']}"
            if path:
                full_name = f"{path} > {full_name}"
            print(f"[ID={btn['id']}] {full_name}")

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())


