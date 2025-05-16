# run.py
from app.app import app, init_db

if __name__ == '__main__':
    init_db()
     # берём порт из окружения Render или дефолт 80 для локальной отладки
     import os
     port = int(os.environ.get('PORT', 80))
     app.run(host='0.0.0.0', port=port)
