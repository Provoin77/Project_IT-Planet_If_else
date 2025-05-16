from app.app import app, init_db

if __name__ == '__main__':
    # Инициализация БД (если нужно)
    init_db()

    # Получаем порт из переменной окружения (Render подставит свой)
    import os
    port = int(os.environ.get('PORT', 80))

    # Запускаем Flask на 0.0.0.0:PORT
    app.run(host='0.0.0.0', port=port)
