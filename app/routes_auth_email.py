# app/routes_auth_email.py
import time
import random

from flask import (
    Blueprint, render_template, request, session,
    redirect, url_for, flash, current_app
)
from .app import db
from .models import User
from .email_utils import send_email

bp = Blueprint('auth_email', __name__)


# ---- 1) СБРОС ПАРОЛЯ ЧЕРЕЗ EMAIL ----

@bp.route('/reset-password-email', methods=['GET','POST'])
def reset_password_email():
    if request.method=='POST':
        email = request.form['email'].strip()
        user = User.query.filter_by(email=email).first()
        if not user:
            flash('Пользователь с таким email не найден', 'error')
            return redirect(url_for('.reset_password_email'))

        code = f"{random.randint(0,999999):06d}"
        session['pw_reset_email_code']    = code
        session['pw_reset_email_user_id'] = user.id
        session['pw_reset_email_time']    = time.time()
        send_email(
            to=user.email,
            subject='Код для сброса пароля',
            template='reset_code',
            code=code,
            expires_in=60
        )
        return redirect(url_for('.reset_password_email_verify'))

    return render_template('reset_password_email.html')


@bp.route('/reset-password-email/verify', methods=['GET','POST'])
def reset_password_email_verify():
    if 'pw_reset_email_code' not in session:
        return redirect(url_for('.reset_password_email'))

    if request.method=='POST':
        entered = request.form['code'].strip()
        # проверка TTL = 1 час
        if time.time() - session['pw_reset_email_time'] > 3600:
            flash('Код устарел', 'error')
            return redirect(url_for('.reset_password_email'))

        if entered != session['pw_reset_email_code']:
            flash('Неверный код', 'error')
            return redirect(url_for('.reset_password_email_verify'))

        return redirect(url_for('.reset_password_email_new'))

    return render_template('reset_password_email_verify.html')


@bp.route('/reset-password-email/new', methods=['GET','POST'])
def reset_password_email_new():
    if 'pw_reset_email_user_id' not in session:
        return redirect(url_for('.reset_password_email'))

    if request.method=='POST':
        pw  = request.form['password'].strip()
        pw2 = request.form['confirm'].strip()
        if not pw or pw!=pw2:
            flash('Пароли не совпадают', 'error')
            return redirect(request.url)

        user = User.query.get(session['pw_reset_email_user_id'])
        user.set_password(pw)
        db.session.commit()

        # чистим сессию
        for k in ('pw_reset_email_code','pw_reset_email_user_id','pw_reset_email_time'):
            session.pop(k, None)

        flash('Пароль успешно сброшен', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password_email_new.html')


# ---- 2) EMAIL-2FA: подключение/отключение ----

@bp.route('/2fa-email/setup', methods=['GET','POST'])
def email_2fa_setup():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])

    if request.method=='POST':
        # проверка кода
        entered = request.form['code'].strip()
        if entered != session.get('email_2fa_setup_code'):
            flash('Неверный код', 'error')
            return redirect(request.url)

        user.email_2fa_enabled = True
        db.session.commit()
        session.pop('email_2fa_setup_code', None)
        flash('Email-2FA успешно включена', 'success')
        return redirect(url_for('edit_profile'))

    # GET — генерируем код и шлём
    code = f"{random.randint(0,999999):06d}"
    session['email_2fa_setup_code'] = code
    session['email_2fa_setup_time'] = time.time()
    send_email(
        to=user.email,
        subject='Код для подключения 2FA',
        template='2fa_setup',
        code=code,
        expires_in=10
    )
    flash('На вашу почту выслан код для подтверждения 2FA', 'info')
    return render_template('email_2fa_setup.html')


@bp.route('/2fa-email/disable', methods=['POST'])
def email_2fa_disable():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    user.email_2fa_enabled = False
    db.session.commit()
    flash('Email-2FA отключена', 'success')
    return redirect(url_for('edit_profile'))


# ---- 3) EMAIL-2FA: во время входа ----

@bp.route('/email-2fa', methods=['GET','POST'])
def email_two_factor():
    # сюда попадаем после логина, если включена 2FA
    if 'email_2fa_user_id' not in session:
        return redirect(url_for('login'))

    if request.method=='POST':
        entered = request.form['code'].strip()
        if entered == session.get('email_2fa_code'):
            # всё ок — логиним
            session.pop('email_2fa_code', None)
            uid = session.pop('email_2fa_user_id')
            session['user_id']   = uid
            session['user_role'] = session.pop('email_2fa_user_role')
            flash('Вы успешно вошли!', 'success')
            return redirect(url_for('index'))
        flash('Неверный код', 'error')

    return render_template('email_two_factor.html')
