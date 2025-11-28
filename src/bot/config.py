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


def get_config() -> BotConfig:
    """Получает конфигурацию из переменных окружения."""
    # Получаем токен бота
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN не установлен в переменных окружения")
    
    # Получаем ID админов
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    admin_ids = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
    if not admin_ids:
        raise ValueError("ADMIN_IDS не установлен в переменных окружения")
    
    # Получаем уровень логирования
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    # Получаем настройки БД (обязательные)
    db_host = os.getenv("DB_HOST")
    if not db_host:
        raise ValueError("DB_HOST не установлен в переменных окружения")
    
    db_port_str = os.getenv("DB_PORT")
    if not db_port_str:
        raise ValueError("DB_PORT не установлен в переменных окружения")
    try:
        db_port = int(db_port_str)
    except ValueError:
        raise ValueError(f"DB_PORT должен быть числом, получено: {db_port_str}")
    
    db_name = os.getenv("DB_NAME")
    if not db_name:
        raise ValueError("DB_NAME не установлен в переменных окружения")
    
    db_user = os.getenv("DB_USER")
    if not db_user:
        raise ValueError("DB_USER не установлен в переменных окружения")
    
    db_password = os.getenv("DB_PASSWORD")
    if not db_password:
        raise ValueError("DB_PASSWORD не установлен в переменных окружения")
    
    # Получаем настройки DeepSeek (опциональные)
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
    ai_service_url = os.getenv("AI_SERVICE_URL", "https://api.deepseek.com/v1")
    
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
    )



