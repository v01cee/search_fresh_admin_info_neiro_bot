FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY . .

# Создаём пользователя для запуска приложения
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Запускаем бота
CMD ["python", "run_bot.py"]

