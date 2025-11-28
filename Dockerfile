FROM python:3.11-slim

WORKDIR /app

# Очищаем кэш apt перед установкой
RUN apt-get clean && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Устанавливаем только необходимые системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

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

