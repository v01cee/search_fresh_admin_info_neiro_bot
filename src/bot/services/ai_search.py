import aiohttp
import json
import re
from typing import List, Dict, Optional, Tuple

from src.bot.config import get_config
from src.bot.database.buttons import get_all_buttons, get_button_by_id
from src.bot.database.button_steps import get_all_steps_for_buttons


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
    # Пасхалка: особый ответ на слово "жопа" в запросе
    normalized_query = (query or "").strip().lower()
    if "жопа" in normalized_query:
        return (
            "Все совсем плохо? Ты держись, сгоняй к руководителю и обсудите, в чём жопа!",
            [],
        )

    config = get_config()
    
    # Получаем ВСЕ кнопки рекурсивно (включая вложенные)
    all_buttons = await get_all_buttons_recursive()
    
    if not all_buttons:
        return None, []
    
    # Оптимизация: создаем словарь кнопок для быстрого доступа
    buttons_dict = {btn["id"]: btn for btn in all_buttons}
    
    # Оптимизация: получаем все шаги одним запросом
    button_ids = [btn["id"] for btn in all_buttons]
    all_steps = await get_all_steps_for_buttons(button_ids)
    
    # Формируем полный список кнопок для AI с информацией о родителях и всем текстовым контентом
    buttons_info = []
    for btn in all_buttons:
        btn_text = btn.get("text", "")
        btn_message = btn.get("message_text", "")
        parent_id = btn.get("parent_id")
        
        # Получаем шаги из кэша (уже загружены одним запросом)
        steps = all_steps.get(btn["id"], [])
        steps_texts = []
        steps_files_info = []
        for step in steps:
            step_text = step.get("content_text", "")
            if step_text:
                steps_texts.append(step_text)
            
            # Учитываем файлы в шагах
            step_file_type = step.get("file_type")
            if step_file_type:
                file_info = f"Файл типа {step_file_type}"
                if step_text:
                    file_info += f": {step_text}"
                steps_files_info.append(file_info)
        
        # Учитываем файл самой кнопки
        btn_file_type = btn.get("file_type")
        btn_file_info = ""
        if btn_file_type:
            btn_file_info = f"Файл типа {btn_file_type}"
            if btn_message:
                btn_file_info += f": {btn_message}"
        
        # Объединяем весь текстовый контент: название + сообщение + шаги + файлы
        all_text_content = []
        if btn_text:
            all_text_content.append(f"Название: {btn_text}")
        if btn_message:
            all_text_content.append(f"Сообщение: {btn_message}")
        if btn_file_info:
            all_text_content.append(f"Файл кнопки: {btn_file_info}")
        if steps_texts:
            all_text_content.append(f"Шаги: {' | '.join(steps_texts)}")
        if steps_files_info:
            all_text_content.append(f"Файлы в шагах: {' | '.join(steps_files_info)}")
        
        full_text = " | ".join(all_text_content)
        
        # Оптимизация: строим путь к родителю используя кэш кнопок
        parent_path = ""
        if parent_id:
            path_parts = []
            current_parent_id = parent_id
            while current_parent_id:
                parent_btn = buttons_dict.get(current_parent_id)
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
            "steps": steps_texts,
            "parent_path": parent_path,
            "full_text": full_text,
            "full_info": f"{btn_text}{parent_path} | {full_text}"
        })
    
    # Создаём детальный список для AI
    buttons_list = "\n".join([
        f"{i+1}. {b['full_info']}" 
        for i, b in enumerate(buttons_info)
    ])
    
    prompt = f"""Ты умный помощник для поиска кнопок в боте. Пользователь ищет: "{query}"

Вот полный список всех доступных кнопок в боте с их полным текстовым содержимым (название, сообщение, шаги):
{buttons_list}

Твоя задача:
1. Если запрос пользователя бессмысленный, непонятный или не имеет отношения к кнопкам (например, случайный набор символов, абракадабра) - ответь: "НЕПОНЯТНО"
2. Если запрос понятный, но ничего не подходит - ответь: "НЕТ_РЕЗУЛЬТАТОВ"
3. Если нашёл релевантные кнопки - верни ТОЛЬКО номера самых подходящих кнопок через запятую, например: 1, 3, 5

КРИТИЧЕСКИ ВАЖНО:
- Ищи по ВСЕМУ текстовому содержимому: названиям кнопок, тексту сообщений, тексту всех шагов И описаниям файлов
- Выбирай ТОЛЬКО самые релевантные кнопки, которые точно соответствуют запросу пользователя
- НЕ возвращай все кнопки подряд, даже если они частично совпадают
- Учитывай контекст и семантику: выбирай кнопки, которые наиболее точно отвечают на запрос пользователя
- Если совпадение найдено в тексте сообщения, шагов ИЛИ в описании файла - это релевантный результат
- Если есть точное совпадение - верни его, но также учитывай семантически близкие результаты
- ВАЖНО: если пользователь ищет документ/файл (например, "ДКП", "шаблон", "договор"), ищи в:
  * Названиях файлов и их описаниях в тексте сообщений и шагов
  * Типах файлов (document, photo, video и т.д.)
  * Тексте, который описывает файлы (например, "Шаблон ДКП аукциона")

Пример: если запрос "ДКП" или "договор", ищи в:
- Названиях кнопок
- Тексте сообщений кнопок (может быть "Шаблон ДКП аукциона")
- Тексте всех шагов кнопок (может быть описание файла с ДКП)
- Информации о файлах (если указано "Файл типа document" или описание файла)

Пример: если запрос "руководитель отдела продаж", ищи в:
- Названиях кнопок (например, "Функционал РОП")
- Тексте сообщений кнопок
- Тексте всех шагов кнопок

Выбирай умно и точно по всему текстовому содержимому, включая описания файлов!"""

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
                        
                        # Преобразуем обратно в формат кнопок (используем кэш)
                        final_results = []
                        for btn_info in results:
                            btn = buttons_dict.get(btn_info["id"])
                            if btn:
                                final_results.append(btn)
                        return None, final_results
                    
                    return None, []
                else:
                    error_text = await response.text()
                    return f"Ошибка API: {response.status}", []
                    
    except Exception as e:
        return f"Ошибка при поиске: {e}", []

