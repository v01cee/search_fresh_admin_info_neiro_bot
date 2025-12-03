import asyncio
from typing import Dict, List, Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from src.bot.config import get_config
from src.bot.database.db import init_db, close_db
from src.bot.database.buttons import get_all_buttons
from src.bot.database.button_steps import get_all_steps_for_buttons


async def _get_all_buttons_recursive(parent_id: Optional[int] = None) -> List[Dict]:
    """
    Рекурсивно получить все кнопки (включая вложенные).
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


async def _check_file(bot: Bot, file_id: str) -> Tuple[bool, Optional[str]]:
    """
    Проверяет, доступен ли файл по file_id через Telegram API.
    Возвращает (is_ok, error_text).
    """
    try:
        await bot.get_file(file_id)
        return True, None
    except TelegramBadRequest as e:
        # 400 / file not found / wrong file_id и т.п.
        return False, str(e)
    except Exception as e:
        # Любая другая ошибка тоже считаем проблемой
        return False, str(e)


async def main() -> None:
    """
    Скрипт для поиска ТОЛЬКО тех кнопок/шагов, где реально будет ошибка при отправке файла:
    - берём все кнопки и шаги, у которых есть file_id
    - для каждого уникального file_id вызываем Telegram API (getFile)
    - если Telegram возвращает ошибку, считаем файл "битым"
    - выводим список кнопок/шагов, которые ссылаются на битые файлы
    """
    config = get_config()
    bot = Bot(token=config.token)

    await init_db()
    try:
        all_buttons = await _get_all_buttons_recursive()
        if not all_buttons:
            print("Кнопок в базе не найдено.")
            return

        button_ids = [b["id"] for b in all_buttons]
        steps_by_button = await get_all_steps_for_buttons(button_ids)
        parent_paths = _build_parent_paths(all_buttons)

        # Собираем все file_id из кнопок и шагов
        usage_by_file_id: Dict[str, List[Dict]] = {}

        for btn in all_buttons:
            file_id = btn.get("file_id")
            file_type = btn.get("file_type")
            if file_id:
                usage_by_file_id.setdefault(file_id, []).append(
                    {
                        "kind": "button",
                        "button_id": btn["id"],
                        "file_type": file_type,
                    }
                )

        for btn_id, steps in steps_by_button.items():
            for step in steps:
                file_id = step.get("file_id")
                file_type = step.get("file_type")
                if file_id:
                    usage_by_file_id.setdefault(file_id, []).append(
                        {
                            "kind": "step",
                            "button_id": btn_id,
                            "step_number": step.get("step_number"),
                            "file_type": file_type,
                        }
                    )

        if not usage_by_file_id:
            print("Ни одна кнопка/шаг не содержит file_id.")
            return

        print(f"Всего уникальных file_id: {len(usage_by_file_id)}")

        broken_files: Dict[str, str] = {}

        # Проверяем каждый уникальный file_id через Telegram
        for idx, (file_id, usages) in enumerate(usage_by_file_id.items(), start=1):
            ok, err = await _check_file(bot, file_id)
            status = "OK" if ok else "BROKEN"
            print(f"[{idx}/{len(usage_by_file_id)}] {status} file_id={file_id!r}")
            if not ok:
                broken_files[file_id] = err or "unknown error"

        if not broken_files:
            print("\nВсе file_id валидны, ошибок при отправке файлов быть не должно.")
            return

        print("\nНайдены битые файлы (Telegram возвращает ошибку getFile):")
        for file_id, err in broken_files.items():
            print(f"\nfile_id={file_id!r}")
            print(f"  Ошибка: {err}")
            print("  Используется в:")

            for usage in usage_by_file_id[file_id]:
                btn_id = usage["button_id"]
                path = parent_paths.get(btn_id) or ""
                # Ищем саму кнопку, чтобы взять текст
                btn = next((b for b in all_buttons if b["id"] == btn_id), None)
                title = (btn.get("text") if btn else None) or f"#{btn_id}"
                full_name = f"{path} > {title}" if path else title

                if usage["kind"] == "button":
                    print(f"    - Кнопка [ID={btn_id}] {full_name} (file_type={usage.get('file_type')})")
                else:
                    step_num = usage.get("step_number")
                    print(
                        f"    - Шаг #{step_num} кнопки [ID={btn_id}] {full_name} "
                        f"(file_type={usage.get('file_type')})"
                    )
    finally:
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())


