import aiohttp
import json
import re
from typing import List, Dict, Optional, Tuple

from src.bot.config import get_config
from src.bot.database.buttons import get_all_buttons, get_button_by_id


async def get_all_buttons_recursive(parent_id: Optional[int] = None) -> List[Dict]:
    """Получить все кнопки рекурсивно (включая вложенные)."""
    buttons = await get_all_buttons(parent_id=parent_id)
    all_buttons = []
    
    for btn in buttons:
        all_buttons.append(btn)
        # Рекурсивно получаем дочерние кнопки
        child_buttons = await get_all_buttons_recursive(parent_id=btn["id"])
        all_buttons.extend(child_buttons)
    
    return all_buttons


async def ai_search_buttons(query: str) -> Tuple[Optional[str], List[Dict]]:
    """
    AI-поиск кнопок через DeepSeek.
    Возвращает (error_message, results):
    - Если error_message не None - это сообщение об ошибке (бессмысленный запрос)
    - Если error_message None - results содержит найденные кнопки
    """
    config = get_config()
    
    # Получаем ВСЕ кнопки рекурсивно (включая вложенные)
    all_buttons = await get_all_buttons_recursive()
    
    if not all_buttons:
        return None, []
    
    # Формируем полный список кнопок для AI с информацией о родителях
    buttons_info = []
    for btn in all_buttons:
        btn_text = btn.get("text", "")
        btn_message = btn.get("message_text", "")
        parent_id = btn.get("parent_id")
        
        parent_path = ""
        if parent_id:
            # Строим путь к родителю
            current_parent_id = parent_id
            path_parts = []
            while current_parent_id:
                parent_btn = await get_button_by_id(current_parent_id)
                if parent_btn:
                    path_parts.insert(0, parent_btn["text"])
                    current_parent_id = parent_btn.get("parent_id")
                else:
                    break
            if path_parts:
                parent_path = f" (внутри: {' > '.join(path_parts)})"
        
        buttons_info.append({
            "id": btn["id"],
            "text": btn_text,
            "message": btn_message,
            "parent_path": parent_path,
            "full_info": f"{btn_text}{parent_path}" + (f" - {btn_message[:100]}" if btn_message else "")
        })
    
    # Создаём детальный список для AI
    buttons_list = "\n".join([
        f"{i+1}. {b['full_info']}" 
        for i, b in enumerate(buttons_info)
    ])
    
    prompt = f"""Ты умный помощник для поиска кнопок в боте. Пользователь ищет: "{query}"

Вот полный список всех доступных кнопок в боте:
{buttons_list}

Твоя задача:
1. Если запрос пользователя бессмысленный, непонятный или не имеет отношения к кнопкам (например, случайный набор символов, абракадабра) - ответь: "НЕПОНЯТНО"
2. Если запрос понятный, но ничего не подходит - ответь: "НЕТ_РЕЗУЛЬТАТОВ"
3. Если нашёл релевантные кнопки - верни ТОЛЬКО номера самых подходящих кнопок через запятую, например: 1, 3, 5

КРИТИЧЕСКИ ВАЖНО:
- Выбирай ТОЛЬКО самые релевантные кнопки, которые точно соответствуют запросу пользователя
- НЕ возвращай все кнопки подряд, даже если они частично совпадают
- Если пользователь ищет "руководитель отдела продаж", выбирай только кнопки, которые напрямую связаны с руководителем отдела продаж, а не все кнопки, где есть слово "отдел" или "продаж"
- Учитывай контекст и семантику: выбирай кнопки, которые наиболее точно отвечают на запрос пользователя
- Если есть точное совпадение по названию - верни только его, не добавляй похожие кнопки

Пример: если запрос "руководитель отдела продаж", а есть кнопки:
- "Функционал РОП" (Руководитель Отдела Продаж) - это подходит
- "Компетенции Руководителя отдела" - это может подходить, если это про руководителя отдела продаж
- "Отделы вовлеченные в продажи" - это НЕ подходит напрямую, не возвращай её

Выбирай умно и точно!"""

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Authorization": f"Bearer {config.deepseek_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты помощник для поиска кнопок. Если запрос непонятный - отвечай 'НЕПОНЯТНО'. Если ничего не найдено - отвечай 'НЕТ_РЕЗУЛЬТАТОВ'. Если нашёл кнопки - отвечай только номерами через запятую."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "max_tokens": 200
            }
            
            async with session.post(
                f"{config.ai_service_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    ai_response = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip().upper()
                    
                    # Проверяем на бессмысленный запрос
                    if "НЕПОНЯТНО" in ai_response or "НЕ ПОНЯЛ" in ai_response or "НЕПОНЯТ" in ai_response:
                        return "Я Вас не понял, можете перефразировать", []
                    
                    # Проверяем на отсутствие результатов
                    if "НЕТ_РЕЗУЛЬТАТОВ" in ai_response or "НЕТ РЕЗУЛЬТАТОВ" in ai_response or not ai_response:
                        return None, []
                    
                    # Парсим номера кнопок
                    numbers = re.findall(r'\d+', ai_response)
                    if numbers:
                        result_indices = [int(n) - 1 for n in numbers if 0 <= int(n) - 1 < len(buttons_info)]
                        results = [buttons_info[i] for i in result_indices if i < len(buttons_info)]
                        
                        # Преобразуем обратно в формат кнопок
                        final_results = []
                        for btn_info in results:
                            btn = await get_button_by_id(btn_info["id"])
                            if btn:
                                final_results.append(btn)
                        return None, final_results
                    
                    return None, []
                else:
                    error_text = await response.text()
                    return f"Ошибка API: {response.status}", []
                    
    except Exception as e:
        return f"Ошибка при поиске: {e}", []

