# telegram_bot.py

import os
import time
from itsdangerous import URLSafeTimedSerializer
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

# ── Импорт вашего Flask-приложения и БД ─────────────────────────────────────
from app.app import app, db
from app.models import User, OrganizerSubscription

# ── Ждём, пока Postgres поднимется ───────────────────────────────────────────
for _ in range(30):
    try:
        with app.app_context():
            db.session.execute(text("SELECT 1"))
        print("✅ Подключились к БД")
        break
    except OperationalError:
        print("⏳ Ждём базу данных…")
        time.sleep(1)
else:
    print("❌ Не удалось подключиться к БД, выхожу")
    exit(1)

# ── Домен приложения ──────────────────────────────────────────────────────────
_raw = os.getenv('APP_DOMAIN', '').strip()
if not _raw:
    _raw = '127.0.0.1:80'
if _raw.startswith(('http://','https://')):
    DOMAIN = _raw.rstrip('/')
else:
    DOMAIN = f'http://{_raw}'

# ── Настройки бота ───────────────────────────────────────────────────────────
BOT_TOKEN  = os.getenv('TELEGRAM_BOT_TOKEN')
BOT         = Bot(token=BOT_TOKEN)
serializer  = URLSafeTimedSerializer(app.config['SECRET_KEY'])

def send_message(chat_id: int, text: str):
    """
    Отправить текстовое сообщение в Telegram.
    """
    try:
        BOT.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"Не удалось отправить ТГ-сообщение {chat_id}: {e}")

def generate_reset_token(user_id: int) -> str:
    return serializer.dumps(user_id, salt='password-reset-salt')

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "👋 Привет! Я бот вашего сервиса.\n"
        "/start — приветствие\n"
        "/help  — команды\n"
        "/reset — ссылка для сброса пароля\n"
        "/follow <username> — подписаться на организатора\n"
        "/unfollow <username> — отписаться"
    )

def help_cmd(update: Update, context: CallbackContext):
    update.message.reply_text(
        "/start — запустить бота\n"
        "/help  — подсказка\n"
        "/reset — получить ссылку для сброса пароля\n"
        "/follow <username> — подписаться на организатора\n"
        "/unfollow <username> — отписаться"
    )

def reset_cmd(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    with app.app_context():
        user = User.query.filter_by(telegram_id=str(chat_id)).first()
    if not user:
        return update.message.reply_text(
            "❗ Сначала привяжите Telegram в вашем профиле на сайте."
        )
    token = generate_reset_token(user.id)
    link  = f"{DOMAIN}/reset-password/{token}"
    update.message.reply_text("🔐 Сброс пароля: " + link)

def follow(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not context.args:
        return update.message.reply_text("Используйте: /follow <username_организатора>")
    username = context.args[0]
    with app.app_context():
        me  = User.query.filter_by(telegram_id=str(chat_id)).first()
        org = User.query.filter_by(username=username, role='organizer').first()

        if not me:
            return update.message.reply_text("❗ Привяжите Telegram в профиле на сайте.")
        if not org:
            return update.message.reply_text("❗ Организатор не найден.")
        if org.id == me.id:
            return update.message.reply_text("❗ Нельзя подписаться на себя.")

        exists = OrganizerSubscription.query.filter_by(
            user_id=me.id, organizer_id=org.id
        ).first()
        if exists:
            return update.message.reply_text("ℹ️ Вы уже подписаны.")

        sub = OrganizerSubscription(user_id=me.id, organizer_id=org.id)
        db.session.add(sub)
        db.session.commit()
        update.message.reply_text(f"✅ Подписались на «{org.org_name}».")

def unfollow(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if not context.args:
        return update.message.reply_text("Используйте: /unfollow <username_организатора>")
    username = context.args[0]
    with app.app_context():
        me  = User.query.filter_by(telegram_id=str(chat_id)).first()
        org = User.query.filter_by(username=username, role='organizer').first()

        if not me or not org:
            return update.message.reply_text(
                "❗ Проверьте, что вы привязаны и указали правильный username."
            )
        sub = OrganizerSubscription.query.filter_by(
            user_id=me.id, organizer_id=org.id
        ).first()
        if not sub:
            return update.message.reply_text("ℹ️ Вы не были подписаны.")

        db.session.delete(sub)
        db.session.commit()
        update.message.reply_text(f"✅ Отписались от «{org.org_name}».")

def main():
    BOT.delete_webhook()

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start",    start))
    dp.add_handler(CommandHandler("help",     help_cmd))
    dp.add_handler(CommandHandler("reset",    reset_cmd))
    dp.add_handler(CommandHandler("follow",   follow))
    dp.add_handler(CommandHandler("unfollow", unfollow))

    # 2) Стартуем polling и сбрасываем все pending updates
    updater.start_polling(drop_pending_updates=True)
    print("🚀 Telegram-бот запущен")
    updater.idle()

if __name__ == '__main__':
    main()
