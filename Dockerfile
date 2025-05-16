# Базовый образ
FROM python:3.10-slim

# Установка необходимых пакетов (netcat и curl)
RUN apt-get update && \
    apt-get install -y netcat-openbsd curl tzdata && \
    rm -rf /var/lib/apt/lists/*


# Рабочая директория
WORKDIR /app

# Копируем зависимости и устанавливаем
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Даем права на выполнение wait-for-it.sh
RUN chmod +x wait-for-it.sh

# Открываем порт
EXPOSE 80

# Переменные окружения
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_DEBUG=1

# Запуск: ждем PostgreSQL и стартуем Flask
CMD ["sh", "-c", "./wait-for-it.sh db:5432 --timeout=120 --strict -- python run.py"]
