import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


@dataclass
class BotConfig:
    token: str
    admin_ids: List[int]
    log_level: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    deepseek_api_key: Optional[str]
    ai_service_url: str
    feedback_chat_id: Optional[int]


def get_config() -> BotConfig:
    """Получает конфигурацию из переменных окружения или использует значения по умолчанию."""
    # Значения по умолчанию (без реальных данных, всё берём из .env / окружения)
    DEFAULT_TOKEN = "CHANGE_ME_BOT_TOKEN"
    DEFAULT_ADMIN_IDS = [5818121757, 177260006, 1283802964]
    DEFAULT_LOG_LEVEL = "INFO"
    # Локальные/демо-настройки БД. Реальные значения задавай через переменные окружения или .env
    DEFAULT_DB_HOST = "localhost"
    DEFAULT_DB_PORT = 5432
    DEFAULT_DB_NAME = "postgres"
    DEFAULT_DB_USER = "postgres"
    DEFAULT_DB_PASSWORD = "CHANGE_ME_DB_PASSWORD"
    # Демо-ключ для AI. Реальный ключ укажи в переменной окружения DEEPSEEK_API_KEY
    DEFAULT_DEEPSEEK_API_KEY = "CHANGE_ME_DEEPSEEK_API_KEY"
    DEFAULT_AI_SERVICE_URL = "https://api.deepseek.com/v1"
    
    # Получаем токен бота (приоритет у переменной окружения)
    token = os.getenv("BOT_TOKEN", DEFAULT_TOKEN)
    
    # Получаем ID админов
    admin_ids_str = os.getenv("ADMIN_IDS")
    if admin_ids_str:
        admin_ids = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
        if not admin_ids:
            admin_ids = DEFAULT_ADMIN_IDS
    else:
        admin_ids = DEFAULT_ADMIN_IDS
    
    # Получаем уровень логирования
    log_level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
    
    # Получаем настройки БД
    db_host = os.getenv("DB_HOST", DEFAULT_DB_HOST)
    
    db_port_str = os.getenv("DB_PORT")
    if db_port_str:
        try:
            db_port = int(db_port_str)
        except ValueError:
            db_port = DEFAULT_DB_PORT
    else:
        db_port = DEFAULT_DB_PORT
    
    db_name = os.getenv("DB_NAME", DEFAULT_DB_NAME)
    db_user = os.getenv("DB_USER", DEFAULT_DB_USER)
    db_password = os.getenv("DB_PASSWORD", DEFAULT_DB_PASSWORD)
    
    # Получаем настройки DeepSeek (опционально)
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", DEFAULT_DEEPSEEK_API_KEY)
    ai_service_url = os.getenv("AI_SERVICE_URL", DEFAULT_AI_SERVICE_URL)

    # Чат для обратной связи (группа/канал)
    feedback_chat_id: Optional[int] = None
    feedback_chat_id_str = os.getenv("FEEDBACK_GROUP_ID") or os.getenv("FEEDBACK_CHAT_ID")
    if feedback_chat_id_str:
        try:
            feedback_chat_id = int(feedback_chat_id_str)
        except ValueError:
            feedback_chat_id = None
    
    return BotConfig(
        token=token,
        admin_ids=admin_ids,
        log_level=log_level,
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        deepseek_api_key=deepseek_api_key,
        ai_service_url=ai_service_url,
        feedback_chat_id=feedback_chat_id,
    )



