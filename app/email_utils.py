# app/email_utils.py
import os
from flask import render_template, current_app
from flask_mail import Message
from .app import mail

def send_email(to: str, subject: str, template: str, **context):
    """
    to: recipient
    subject: тема письма
    template: имя шаблона из templates/email/{template}.(html|txt)
    context: передача кода, ссылок и т.п.
    """
    msg = Message(subject=subject, recipients=[to])
    msg.body = render_template(f'email/{template}.txt', **context)
    msg.html = render_template(f'email/{template}.html', **context)
    mail.send(msg)
