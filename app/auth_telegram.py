# app/auth_telegram.py

import os
import hmac
import hashlib
import time
import random
import requests

from itsdangerous import URLSafeTimedSerializer
from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, current_app, flash, abort
)
# Импортируем db из app.app, а не из app/__init__.py
from app.app import db
from app.models import User
from sqlalchemy.exc import IntegrityError
auth_bp = Blueprint('auth_telegram', __name__)

# --- Проверка данных из Telegram Login Widget по HMAC ---
def verify_telegram(data: dict) -> bool:
    check_hash = data.pop('hash', '')
    data_check = '\n'.join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hashlib.sha256(current_app.config['TELEGRAM_BOT_TOKEN'].encode()).digest()
    hmac_hash = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(hmac_hash, check_hash):
        return False
    return (time.time() - int(data.get('auth_date', 0))) < 86400

# --- Генерация и проверка токена для сброса пароля ---
def generate_reset_token(user_id: int) -> str:
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(user_id, salt='password-reset-salt')

def verify_reset_token(token: str, expiration: int = 3600):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        user_id = s.loads(token, salt='password-reset-salt', max_age=expiration)
    except Exception:
        return None
    return User.query.get(user_id)

# --- 1. Кнопка Telegram Login Widget ---
@auth_bp.route('/login/telegram')
def login_telegram():
    bot_user = current_app.config.get('TELEGRAM_BOT_USERNAME')
    if not bot_user:
        abort(500, 'Bot username required')
    return render_template('telegram_login.html', bot_username=bot_user)

@auth_bp.route('/link/telegram')
def link_telegram():
    # помечаем, что сейчас идёт именно привязка, а не вход
    session['binding_telegram'] = True
    return redirect(url_for('auth_telegram.login_telegram'))

# --- 2. Callback от Telegram Login Widget ---
@auth_bp.route('/login/telegram/callback')
def telegram_callback():
    data = request.args.to_dict()
    if not verify_telegram(data.copy()):
        flash('Некорректные данные из Telegram.', 'error')
        return redirect(url_for('login'))

    tg_id_str = str(data['id'])
    username  = data.get('username') or f"tg_{tg_id_str}"
    full_name = ' '.join(filter(None, [data.get('first_name'), data.get('last_name')]))

    # --- СЦЕНАРИЙ ПРИВЯЗКИ ---
    if session.pop('binding_telegram', False):
        # проверяем, что пользователь залогинен и является участником
        if 'user_id' not in session or session.get('user_role') != 'participant':
            flash('Сначала войдите на сайт, затем кликайте по «Привязать Telegram».', 'error')
            return redirect(url_for('login'))

        user = User.query.get(session['user_id'])
        if not user:
            flash('Пользователь из сессии не найден.', 'error')
            return redirect(url_for('login'))

        # пытаемся сохранить привязку
        user.telegram_id    = tg_id_str
        user.telegram_login = username
        try:
            db.session.commit()
            flash('✅ Telegram успешно привязан к вашему профилю.', 'success')
        except IntegrityError as e:
            db.session.rollback()
            # если кто-то уже привязал этот tg_id
            if 'users_telegram_id_key' in str(e.orig):
                flash(
                    'Этот Telegram-аккаунт уже привязан к другому профилю. '
                    'Если это ошибка, свяжитесь с администрацией.',
                    'error'
                )
            else:
                flash('Не удалось привязать Telegram: внутренняя ошибка.', 'error')

        return redirect(url_for('edit_profile'))

    # --- СЦЕНАРИЙ ВХОДА через Telegram Login Widget ---
    user = User.query.filter_by(telegram_id=tg_id_str).first()
    if not user:
        # первый раз – создаём нового участника
        user = User(
            telegram_id    = tg_id_str,
            telegram_login = username,
            username       = username,
            full_name      = full_name,
            email          = f"tg_{tg_id_str}@telegram",
            role           = 'participant'
        )
        user.set_password(os.urandom(16).hex())
        db.session.add(user)
        db.session.commit()

    # двухфакторка: генерируем и шлём код
    code = f"{random.randint(0, 999999):06d}"
    session['2fa_user_id']   = user.id
    session['2fa_user_role'] = user.role
    session['2fa_code']      = code

    requests.post(
        f"https://api.telegram.org/bot{current_app.config['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={'chat_id': data['id'], 'text': f"Ваш код для входа: {code}"}
    )
    return redirect(url_for('auth_telegram.two_factor'))



# --- 3. Ввод 2FA-кода ---
@auth_bp.route('/2fa', methods=['GET', 'POST'])
def two_factor():
    if '2fa_user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        entered = request.form.get('code', '').strip()
        if entered == session.get('2fa_code'):
            # Переносим в основную сессию и чистим временные данные
            session.pop('2fa_code', None)
            session['user_id']   = session.pop('2fa_user_id')
            session['user_role'] = session.pop('2fa_user_role')
            flash('Вы успешно вошли!', 'success')
            return redirect(url_for('index'))
        flash('Неверный код', 'error')

    return render_template('two_factor.html')

# --- Сброс пароля по ссылке ---
@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = verify_reset_token(token)
    if not user:
        flash("Ссылка устарела или неверна.", 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        pw  = request.form.get('password', '').strip()
        pw2 = request.form.get('confirm', '').strip()
        if not pw or pw != pw2:
            flash("Пароли не совпадают.", 'error')
        else:
            user.set_password(pw)
            db.session.commit()
            flash("Пароль успешно сброшен.", 'success')
            return redirect(url_for('login'))

    return render_template('reset_password.html', token=token)
