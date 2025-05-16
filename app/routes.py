from flask import render_template, request, jsonify, redirect, session, url_for, abort, json, current_app, send_from_directory, flash
from datetime import datetime, timedelta
import os
import pytz
import time
import re


from app.app import app, db, limiter, ALLOWED_IMG_EXT

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# достаём из конфигурации Flask (app), а не current_app
UPLOAD_FOLDER = os.path.join(app.static_folder, 'uploads', 'reviews')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


from telegram_bot import send_message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_
from app.recommendations import generate_recommendations_for_user


def allowed_file(filename):
    ext = filename.rsplit('.', 1)[-1].lower()
    return '.' in filename and ext in ALLOWED_EXTENSIONS

#MOSCOW_TZ = pytz.timezone('Europe/Moscow')


# Контекстный процессор для передачи текущего пользователя в шаблоны
@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    return {'current_user': user}

@app.context_processor
def inject_datetime():
    from datetime import datetime
    return dict(datetime=datetime)


# Главная страница: отображение карты и списка мероприятий


from flask import render_template, request, jsonify, redirect, session, url_for, abort, json, current_app, send_from_directory, flash
from datetime import datetime
import os
from app.app import app, db
from app.models import User, Event, EventType, EventSphere, Friendship, EventSubscription, Favorite, Notification, Review, OrganizerSubscription, Personality, Event, event_personalities, UserRecommendation


import random
from app.email_utils import send_email

@app.route('/')
@limiter.exempt
def index():
    now = datetime.now()

    # Все одобренные мероприятия, отсортированные по дате
    events_all = (
        Event.query
             .filter(Event.is_approved == True)
             .order_by(Event.priority.desc(), Event.date.asc())
             .all()
    )
    filtered_events = []
    markers = []

    # Подписки текущего участника
    user_sub_ids = []
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.role == 'participant':
            user_sub_ids = [sub.event_id for sub in user.subscriptions]

    for ev in events_all:
        # Вычисляем конец мероприятия
        try:
            hours, minutes = map(int, ev.duration.split(':'))
            event_end = ev.date + timedelta(hours=hours, minutes=minutes)
        except Exception:
            event_end = ev.date

        # Статус
        if now < ev.date:
            status = "предстоит"
        elif ev.date <= now < event_end:
            status = "проходит"
        else:
            status = "прошло"

        # Пропускаем прошедшие
        if status == "прошло":
            continue

        ev.filtered_status = status

        markers.append({
            'id': ev.id,
            'title': ev.title,
            'lat': ev.lat,
            'lon': ev.lon,
            'organizer': ev.creator.org_name if ev.creator else '',
            'event_format': ev.event_format,
            'city': ev.city,
            'address': ev.address,
            'date': ev.date.strftime("%d.%m.%Y %H:%M"),
            'status': status,
            'subscribed': (ev.id in user_sub_ids),
            'event_sphere': ev.event_sphere,
            'event_type': ev.event_type,
            'has_personality': bool(ev.personalities),
            'personalities': [p.name for p in ev.personalities],
            'priority': ev.priority,
            'image_filename': ev.image_filename,
        })
        filtered_events.append(ev)

    events_json = json.dumps(markers, ensure_ascii=False)

    # Собираем избранное участника
    favorites = []
    if 'user_id' in session:
        u = User.query.get(session['user_id'])
        if u and u.role == 'participant':
            favorites = [
                {'type': f.fav_type, 'value': f.fav_value}
                for f in u.favorites
            ]
    favorites_json = json.dumps(favorites, ensure_ascii=False)

    map_key = os.environ.get('YANDEX_MAPS_API_KEY', '')
    event_types   = EventType.query.all()
    event_spheres = EventSphere.query.all()

    return render_template(
        'index.html',
        events=filtered_events,
        events_json=events_json,
        favorites_json=favorites_json,
        map_api_key=map_key,
        event_types=event_types,
        event_spheres=event_spheres,
        now=now
    )


@app.route('/register', methods=['GET', 'POST'])
@limiter.exempt
def register():
    if request.method == 'POST':
        # Общие поля
        email = request.form['email'].strip()
        password = request.form['password']
        confirm = request.form['confirm_password']
        role = request.form.get('role', 'participant')
        error = None

        # Базовая валидация
        if not email or not password:
            error = "Заполните обязательные поля."
        elif password != confirm:
            error = "Пароли не совпадают."
        elif User.query.filter_by(email=email).first():
            error = "Email уже зарегистрирован."

        # Поля для участника
        if not error and role == 'participant':
            username = request.form.get('username', '').strip()
            full_name = request.form.get('full_name', '').strip()
            if not username:
                error = "Введите имя пользователя."
            elif User.query.filter_by(username=username).first():
                error = "Имя пользователя уже занято."
            elif not full_name:
                error = "Введите Ваше имя."

        # Поля для организатора
        if not error and role == 'organizer':
            org_name = request.form.get('org_name', '').strip()
            org_description = request.form.get('org_description', '').strip()
            org_sphere = request.form.get('org_sphere', '').strip()
            org_phone = request.form.get('org_phone', '').strip()
            accred_file = request.files.get('accreditation_image')
            if not org_name or not org_description or not org_sphere or not org_phone:
                error = "Заполните все поля для регистрации организатора."
            elif not accred_file:
                error = "Необходимо загрузить изображение аккредитации."

        if error:
            return render_template('register.html', error=error)

        # Создаём пользователя
        new_user = User(email=email, role=role)
        if role == 'participant':
            new_user.username = username
            new_user.full_name = full_name
        else:  # organizer
            new_user.username         = org_name
            new_user.org_name         = org_name
            new_user.org_description  = org_description
            new_user.org_sphere       = org_sphere
            new_user.org_phone        = org_phone
            # Сохраняем файл аккредитации
            if accred_file:
                fn = secure_filename(accred_file.filename)
                folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, fn)
                accred_file.save(path)
                new_user.accreditation_image = fn
            new_user.org_approved = False

        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        # Уведомляем модераторов о новой заявке организатора
        if role == 'organizer':
            mods = User.query.filter_by(role='moderator').all()
            for mod in mods:
                note = Notification(
                    user_id=mod.id,
                    message=f"Регистрация организатора «{org_name}» требует модерации.",
                    url=url_for('list_organizers')
                )
                db.session.add(note)
            db.session.commit()

        # Логиним пользователя
        session['user_id']   = new_user.id
        session['user_role'] = new_user.role

        # Редирект в зависимости от роли
        if role == 'organizer':
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('index'))

    # GET-запрос — показываем форму регистрации
    return render_template('register.html')



# Авторизация пользователя
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user.is_blocked:
            return render_template('login.html', error=f"Ваш аккаунт заблокирован: {user.block_reason}")
        if user and user.check_password(password):
            # если Email-2FA включена — отправляем код и переходим на ввод
            if user.email_2fa_enabled:
                code = f"{random.randint(0,999999):06d}"
                session['email_2fa_code']      = code
                session['email_2fa_user_id']   = user.id
                session['email_2fa_user_role'] = user.role
                send_email(
                    to=user.email,
                    subject='Код для входа (Email-2FA)',
                    template='2fa_login',
                    code=code,
                    expires_in=10
                )
                return redirect(url_for('auth_email.email_two_factor'))

            # иначе — обычный вход
            session['user_id'] = user.id
            session['user_role'] = user.role
            if user.role in ['organizer', 'moderator']:
                return redirect(url_for('dashboard'))
            return redirect(url_for('index'))

        error = "Неправильные учетные данные."
        return render_template('login.html', error=error)
    return render_template('login.html')


@app.route('/logout')
@limiter.exempt
def logout():
    session.clear()
    return redirect(url_for('index'))

from flask import g, redirect, url_for, flash
from functools import wraps

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kw):
        if g.user is None:
            flash("Сначала войдите в систему", "error")
            return redirect(url_for('login'))
        return f(*args, **kw)
    return wrapper

# Личный кабинет / панель модератора
@app.route('/dashboard')
@limiter.exempt
def dashboard():
    # Если не залогинен — на страницу входа
    if not session.get('user_id'):
        return redirect(url_for('login'))
    # Роль берём из сессии, а не из g.user
    role = session.get('user_role')
    if role == 'organizer':
        # Получаем мероприятия, созданные данным организатором
        my_events = Event.query.filter_by(creator_id=session['user_id']).order_by(Event.date).all()
        now = datetime.now()  #возвращаем московское время

        # Группы для сортировки событий
        moderation = []
        upcoming = []
        current = []
        past = []

        for ev in my_events:
            if not ev.is_approved:
                ev.filtered_status = "на модерации"
                moderation.append(ev)
            else:
                try:
                    hours, minutes = map(int, ev.duration.split(':'))
                    duration_td = timedelta(hours=hours, minutes=minutes)
                except Exception:
                    duration_td = timedelta(0)
                event_end = ev.date + duration_td
                if now < ev.date:
                    status = "предстоит"
                elif ev.date <= now < event_end:
                    status = "проходит"
                else:
                    status = "прошло"
                ev.filtered_status = status

                if status == "предстоит":
                    upcoming.append(ev)
                elif status == "проходит":
                    current.append(ev)
                elif status == "прошло":
                    past.append(ev)

        return render_template('dashboard_organizer.html',
                               moderation=moderation,
                               upcoming=upcoming,
                               current=current,
                               past=past)
    elif role == 'participant':
        return render_template('dashboard_participant.html')
    elif role == 'moderator':
        pending_events = Event.query.filter_by(is_approved=False).order_by(Event.date).all()
        return render_template('dashboard_moderator.html', events=pending_events)
    else:
        return redirect(url_for('index'))


@app.route('/participant/profile', methods=['GET', 'POST'])
@limiter.exempt
def edit_profile():
    # только авторизованный участник
    if 'user_id' not in session or session.get('user_role') != 'participant':
        abort(403)
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        # Форма редактирования персональных данных
        if request.form.get('form_type') == 'profile':
            # если дата рождения ещё не задана — можно установить
            if not user.date_of_birth:
                dob = request.form.get('date_of_birth')
                if dob:
                    user.date_of_birth = datetime.strptime(dob, '%Y-%m-%d').date()
            user.telegram_login = request.form.get('telegram_login')
            user.phone_number   = request.form.get('phone_number')
            user.about_me       = request.form.get('about_me')
            user.region = request.form.get('region')
            user.gender         = request.form.get('gender')
            user.skills         = request.form.get('skills')
            db.session.commit()
            flash('Профиль сохранён.', 'success')
            return redirect(url_for('edit_profile'))

        # Форма смены пароля
        elif request.form.get('form_type') == 'password':
            old = request.form.get('old_password')
            new  = request.form.get('new_password')
            conf = request.form.get('confirm_password')
            # Проверяем старый пароль
            if not user.check_password(old):
                flash('Старый пароль неверен.', 'error')
            elif not new or new != conf:
                flash('Новый пароль и подтверждение не совпадают.', 'error')
            else:
                user.set_password(new)
                db.session.commit()
                flash('Пароль успешно изменён.', 'success')
            return redirect(url_for('edit_profile'))

    return render_template('participant_profile.html', user=user)


@app.route('/organizer/profile', methods=['GET', 'POST'])
@limiter.exempt
def organizer_profile():
    # только авторизованный организатор
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        abort(403)
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        # обрабатываем только смену пароля
        if request.form.get('form_type') == 'password':
            old_pw = request.form.get('old_password', '')
            new_pw = request.form.get('new_password', '')
            conf_pw = request.form.get('confirm_password', '')

            if not user.check_password(old_pw):
                flash('Старый пароль неверен.', 'error')
            elif not new_pw or new_pw != conf_pw:
                flash('Новый пароль и подтверждение не совпадают.', 'error')
            else:
                user.set_password(new_pw)
                db.session.commit()
                flash('Пароль успешно изменён.', 'success')

        return redirect(url_for('organizer_profile'))

    # GET — просто отобразить форму
    return render_template(
        'organizer_profile.html',
        user=user,
        accreditation_url=url_for('view_accreditation', user_id=user.id)
    )



# Создание нового мероприятия (только для организатора)
@app.route('/events/new', methods=['GET', 'POST'])
@limiter.exempt
def create_event():
    if session.get('user_role') != 'organizer':
        abort(403)

    user = User.query.get(session['user_id'])
    if not user.org_approved:
        flash("Ваша заявка ещё не одобрена модератором, создание мероприятий недоступно.", "error")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        # 1) Читаем все поля формы
        title        = request.form['title'].strip()
        description  = request.form['description'].strip()
        date_str     = request.form['date']  # "YYYY-MM-DDTHH:MM"
        address      = request.form.get('address', '').strip()
        city         = request.form.get('city', '').strip()
        lat          = request.form.get('lat')
        lon          = request.form.get('lon')
        event_format = request.form.get('event_format')
        duration     = request.form.get('duration')
        event_type   = request.form.get('event_type')
        event_sphere = request.form.get('event_sphere')
        resources    = request.form.get('resources', '').strip()
        priority     = int(request.form.get('priority', 0) or 0)

        # 2) Парсим дату
        try:
            event_date = datetime.fromisoformat(date_str.replace('T', ' '))
        except ValueError:
            flash("Неверный формат даты.", "error")
            return redirect(url_for('create_event'))

        if not title or not description:
            flash("Название и описание обязательны.", "error")
            return redirect(url_for('create_event'))

        # 3) Создаём объект события и сохраняем в сессию
        ev = Event(
            title         = title,
            description   = description,
            date          = event_date,
            address       = address,
            city          = city,
            lat           = float(lat) if lat else None,
            lon           = float(lon) if lon else None,
            event_format  = event_format,
            duration      = duration,
            event_type    = event_type,
            event_sphere  = event_sphere,
            resources     = resources,
            priority      = priority,
            creator_id    = user.id
        )
        db.session.add(ev)
        db.session.flush()  # чтобы получить ev.id до коммита

        # 4) Сохраняем обложку, если есть
        file = request.files.get('image')
        if file and '.' in file.filename and \
           file.filename.rsplit('.', 1)[1].lower() in ALLOWED_IMG_EXT:
            filename = secure_filename(f"{int(time.time())}_{file.filename}")
            file.save(os.path.join(app.config['MEROP_IMAGE_FOLDER'], filename))
            ev.image_filename = filename

        # 5) Финальный коммит
        db.session.commit()

        # Уведомляем модераторов
        mods = User.query.filter_by(role='moderator').all()
        for mod in mods:
            note = Notification(
                user_id=mod.id,
                message=f"Новое мероприятие «{ev.title}» требует модерации.",
                url=url_for('moderator_events')
            )
            db.session.add(note)
        db.session.commit()

        # Обновляем рекомендации
        participants = User.query.filter_by(role='participant').all()
        for participant in participants:
            generate_recommendations_for_user(participant)

        flash("Мероприятие создано и рекомендации обновлены.", "success")
        return redirect(url_for('dashboard'))

    # GET — отрисовать форму
    event_types   = EventType.query.all()
    event_spheres = EventSphere.query.all()
    map_key       = os.getenv('YANDEX_MAPS_API_KEY', '')

    return render_template(
        'event_form.html',
        event         = None,
        event_types   = event_types,
        event_spheres = event_spheres,
        map_api_key   = map_key
    )












# --- Toggle favorite + обновление favorite_count ---
@app.route('/favorites/toggle', methods=['POST'])
@limiter.exempt
def toggle_favorite():
    if 'user_id' not in session or session.get('user_role') != 'participant':
        return jsonify(success=False), 403

    data = request.get_json()
    fav_type = data.get('type')
    fav_value = str(data.get('value'))
    uid = session['user_id']

    existing = Favorite.query.filter_by(
        user_id=uid, fav_type=fav_type, fav_value=fav_value
    ).first()

    # если это событие — обновляем счетчик
    if fav_type == 'event':
        event = Event.query.get_or_404(int(fav_value))
    else:
        event = None

    if existing:
        db.session.delete(existing)
        action = 'removed'
        if event:
            event.favorite_count = max((event.favorite_count or 1) - 1, 0)
    else:
        newf = Favorite(user_id=uid, fav_type=fav_type, fav_value=fav_value)
        db.session.add(newf)
        action = 'added'
        if event:
            event.favorite_count = (event.favorite_count or 0) + 1

    db.session.commit()
    return jsonify(success=True, action=action, type=fav_type, value=fav_value)

@app.route('/events/<int:event_id>')
@limiter.exempt
def view_event(event_id):
    event = Event.query.get_or_404(event_id)

    # Только одобренные или доступ автору/модератору
    if not event.is_approved:
        uid = session.get('user_id')
        role = session.get('user_role')
        if not uid or (role != 'moderator' and uid != event.creator_id):
            abort(404)

    # Инкремент просмотров для участников
    uid = session.get('user_id')
    if uid:
        user = User.query.get(uid)
        if user and user.role == 'participant':
            event.view_count = (event.view_count or 0) + 1
            db.session.commit()

    # Вычисляем статус
    now = datetime.now()
    try:
        h, m = map(int, event.duration.split(':'))
        event_end = event.date + timedelta(hours=h, minutes=m)
    except:
        event_end = event.date

    if now < event.date:
        status = "предстоит"
    elif event.date <= now < event_end:
        status = "проходит"
    else:
        status = "прошло"

    # Проверяем, подписан ли
    subscribed = False
    if uid:
        subscribed = bool(EventSubscription.query.filter_by(
            event_id=event.id, user_id=uid
        ).first())

    # Избранное
    favorites = []
    if uid:
        favs = Favorite.query.filter_by(user_id=uid).all()
        favorites = [{'type': f.fav_type, 'value': f.fav_value} for f in favs]

    # Отзывы
    reviews = Review.query.filter_by(
        event_id=event.id, is_approved=True
    ).order_by(Review.created_at.desc()).all()

    return render_template(
        'event_detail.html',
        event=event,
        event_status=status,
        subscribed=subscribed,
        favorites_json=jsonify(favorites).get_data(as_text=True),
        reviews=reviews
    )

# Редактирование мероприятия

@app.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@limiter.exempt
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if not session.get('user_id') or \
       (session['user_id'] != event.creator_id and session.get('user_role') != 'moderator'):
        abort(403)

    if request.method == 'POST':
        # 1) Обновляем текстовые поля
        event.title        = request.form['title'].strip()
        event.description  = request.form['description'].strip()
        date_str           = request.form['date']
        event.city         = request.form['city'].strip()
        event.address      = request.form['address'].strip()
        event.lat          = float(request.form['lat']) if request.form.get('lat') else None
        event.lon          = float(request.form['lon']) if request.form.get('lon') else None
        event.event_format = request.form['event_format']
        event.duration     = request.form['duration']
        event.event_type   = request.form['event_type']
        event.event_sphere = request.form['event_sphere']
        event.resources    = request.form.get('resources', '').strip()
        event.priority     = int(request.form.get('priority', 0) or 0)

        # 2) Парсим новую дату
        try:
            event.date = datetime.fromisoformat(date_str.replace('T', ' '))
        except ValueError:
            try:
                event.date = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            except:
                event.date = event.date  # оставляем старое, если не получилось

        # 3) Если организатор — сбрасываем флаг одобрения
        if session.get('user_role') == 'organizer':
            event.is_approved = False
            flash("Изменения отправлены на повторную модерацию.", "info")

        # 4) Обработка нового файла
        file = request.files.get('image')
        if file and '.' in file.filename and \
           file.filename.rsplit('.', 1)[1].lower() in ALLOWED_IMG_EXT:
            filename = secure_filename(f"{int(time.time())}_{file.filename}")
            file.save(os.path.join(app.config['MEROP_IMAGE_FOLDER'], filename))
            event.image_filename = filename

        db.session.commit()
        return redirect(url_for('view_event', event_id=event.id))

    # GET — отрисовать форму с текущими данными
    return render_template(
        'event_form.html',
        event           = event,
        organizers_list = User.query.filter_by(role='organizer', org_approved=True).all(),
        event_types     = EventType.query.all(),
        event_spheres   = EventSphere.query.all(),
        map_api_key     = os.getenv('YANDEX_MAPS_API_KEY', '')
    )



@app.route('/events/<int:event_id>/delete', methods=['POST'])
@limiter.exempt
def delete_event(event_id):
    # 1) Найти событие или вернуть 404
    event = Event.query.get_or_404(event_id)

    # 2) Проверить права: только модератор или создатель может удалять
    user_id   = session.get('user_id')
    user_role = session.get('user_role')
    if not user_id or (user_role != 'moderator' and user_id != event.creator_id):
        abort(403)

    # 3) Удалить все подписки (если у вас нет cascade на эту связь)
    EventSubscription.query.filter_by(event_id=event.id).delete()

    # 4) Удалить само событие (каскадно удалятся reviews благодаря настройкам модели)
    db.session.delete(event)

    # 5) Закоммитить всё разом
    db.session.commit()

    # 6) Перенаправить обратно
    if session.get('user_role') == 'moderator':
        return redirect(url_for('moderator_events'))
        # для организатора — на его панель
    elif session.get('user_role') == 'organizer':
        return redirect(url_for('dashboard'))
        # на всякий случай — на главную
    return redirect(url_for('index'))

# Одобрение мероприятия (только для модератора)
@app.route('/events/<int:event_id>/approve', methods=['POST'])
@limiter.exempt
def approve_event(event_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    event = Event.query.get_or_404(event_id)

    # Подтверждаем мероприятие
    event.is_approved = True
    db.session.commit()

    # Уведомляем автора-организатора
    note = Notification(
        user_id=event.creator_id,
        message=f"Ваше мероприятие «{event.title}» успешно одобрено.",
        url=url_for('dashboard')
    )
    db.session.add(note)
    db.session.commit()
    # получаем все подписки на этого организатора
    org_subs = OrganizerSubscription.query.filter_by(
        organizer_id=event.creator_id
    ).all()

    for osub in org_subs:
        user = User.query.get(osub.user_id)

        # 1) Telegram-уведомление
        if user and user.telegram_id:
            base = request.url_root.rstrip('/')
            link = f"{base}{url_for('view_event', event_id=event.id)}"
            text = (
                f"Организатор «{event.creator.org_name}» опубликовал новое мероприятие:\n\n"
                f"{event.title}\n"
                f"{link}"
            )
            send_message(int(user.telegram_id), text)

        # 2) E-mail, только если это валидный SMTP-адрес
        if user and user.email and re.match(r"[^@]+@[^@]+\.[^@]+", user.email):
            base = request.url_root.rstrip('/')
            link = f"{base}{url_for('view_event', event_id=event.id)}"
            send_email(
                to=user.email,
                subject=f"Новое мероприятие от {event.creator.org_name}",
                template='new_event',
                organizer=event.creator.org_name,
                title=event.title,
                link=link
            )

    return redirect(request.referrer or url_for('moderator_events'))



# Маршрут для модерации заявок организаторов (список ожидающих подтверждения)
@app.route('/organizers')
@limiter.exempt
def list_organizers():
    if session.get('user_role') != 'moderator':
        abort(403)
    pending_organizers = User.query.filter_by(role='organizer', org_approved=False).all()
    return render_template('dashboard_organizer_moderation.html', organizers=pending_organizers)

# Одобрение заявки организатора
@app.route('/organizers/<int:user_id>/approve', methods=['POST'])
@limiter.exempt
def approve_organizer(user_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    org = User.query.get_or_404(user_id)
    if org.role != 'organizer':
        abort(400)

    # Подтверждаем организатора
    org.org_approved = True
    db.session.commit()

    # Уведомляем самого организатора
    note = Notification(
        user_id=org.id,
        message="Ваш аккаунт организатора успешно одобрен.",
        url=url_for('dashboard')
    )
    db.session.add(note)
    db.session.commit()

    return redirect(url_for('list_organizers'))

# Отклонение заявки организатора (удаляем аккаунт)
@app.route('/organizers/<int:user_id>/reject', methods=['POST'])
@limiter.exempt
def reject_organizer(user_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    org = User.query.get_or_404(user_id)
    if org.role != 'organizer':
        abort(400)
    db.session.delete(org)
    db.session.commit()
    return redirect(url_for('list_organizers'))


@app.route("/organizers/<int:user_id>/accreditation")
@limiter.exempt
def view_accreditation(user_id):
    # Получаем пользователя-организатора
    user = User.query.get_or_404(user_id)
    current_role = session.get('user_role')
    current_uid  = session.get('user_id')

    # Разрешаем доступ модератору или самому организатору
    if not (
        current_role == 'moderator'
        or (current_role == 'organizer' and current_uid == user_id)
    ):
        abort(403)

    if not user.accreditation_image:
        return "У этого организатора нет загруженного файла аккредитации."

    upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
    filepath = os.path.join(upload_folder, user.accreditation_image)
    if not os.path.exists(filepath):
        return "Файл аккредитации не найден на сервере."

    return send_from_directory(upload_folder, user.accreditation_image)



@app.route('/organizer/events/<int:event_id>/participants')
@limiter.exempt
def organizer_event_participants(event_id):
    # Доступ только для авторизованного организатора‑создателя
    if session.get('user_role') != 'organizer':
        abort(403)
    event = Event.query.get_or_404(event_id)
    if event.creator_id != session['user_id']:
        abort(403)

    # Собираем данные по подпискам
    participants = []
    for sub in event.subscriptions:
        u = sub.participant
        participants.append({
            'full_name': u.full_name or u.username,
            'username':  u.username,
            'email':     u.email,
            'telegram':  getattr(u, 'telegram_login', ''),
            'status':    sub.status
        })

    return render_template(
        'organizer_event_participants.html',
        event=event,
        participants=participants
    )



@app.route('/manage/event_types', methods=['GET', 'POST'])
@limiter.exempt
def manage_event_types():
    if session.get('user_role') not in ['organizer', 'moderator']:
        abort(403)
    if request.method == 'POST':
        new_type = request.form.get('new_type', '').strip()
        if new_type:
            existing = EventType.query.filter_by(name=new_type).first()
            if not existing:
                et = EventType(name=new_type)
                db.session.add(et)
                db.session.commit()
        delete_id = request.form.get('delete_id')
        if delete_id:
            et = EventType.query.get(delete_id)
            if et:
                db.session.delete(et)
                db.session.commit()
        return redirect(url_for('manage_event_types'))
    event_types = EventType.query.all()
    return render_template('manage_event_types.html', event_types=event_types)


@app.route('/manage/event_spheres', methods=['GET', 'POST'])
@limiter.exempt
def manage_event_spheres():
    if session.get('user_role') not in ['organizer', 'moderator']:
        abort(403)
    if request.method == 'POST':
        new_sphere = request.form.get('new_sphere', '').strip()
        if new_sphere:
            existing = EventSphere.query.filter_by(name=new_sphere).first()
            if not existing:
                es = EventSphere(name=new_sphere)
                db.session.add(es)
                db.session.commit()
        delete_id = request.form.get('delete_id')
        if delete_id:
            es = EventSphere.query.get(delete_id)
            if es:
                db.session.delete(es)
                db.session.commit()
        return redirect(url_for('manage_event_spheres'))
    event_spheres = EventSphere.query.all()
    return render_template('manage_event_spheres.html', event_spheres=event_spheres)


# Список всех мероприятий для модератора (с возможностью редактирования и удаления)
@app.route('/moderator/events')
@limiter.exempt
def moderator_events():
    if session.get('user_role') != 'moderator':
        abort(403)
    # Берём ВСЕ мероприятия (и одобренные, и нет)
    events = Event.query.order_by(Event.date).all()
    return render_template('dashboard_moderator_events.html', events=events)


@app.route('/moderator/participants')
@limiter.exempt
def moderator_participants():
    if session.get('user_role') != 'moderator':
        abort(403)
    # Получаем всех участников (role == 'participant')
    participants = User.query.filter_by(role='participant').all()
    return render_template('moderator_participants.html', participants=participants)


@app.route('/moderator/participants/<int:user_id>')
@limiter.exempt
def moderator_participant_detail(user_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    participant = User.query.get_or_404(user_id)
    if participant.role != 'participant':
        abort(400)
    now = datetime.now()
    subscriptions_info = []
    for sub in participant.subscriptions:
        # Вычисляем время окончания мероприятия с учетом продолжительности "HH:MM"
        try:
            hours, minutes = map(int, sub.event.duration.split(':'))
            event_end = sub.event.date + timedelta(hours=hours, minutes=minutes)
        except Exception:
            event_end = sub.event.date
        # Флаг: можно обновить статус только если мероприятие идёт в данный момент
        can_update = (sub.event.date <= now < event_end)
        subscriptions_info.append({
            'subscription': sub,
            'event_end': event_end,
            'can_update': can_update,
        })
    return render_template('moderator_participant_detail.html',
                           participant=participant,
                           subscriptions_info=subscriptions_info,
                           now=now)


@app.route('/moderator/subscription/<int:subscription_id>/update', methods=['POST'])
@limiter.exempt
def update_subscription(subscription_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    sub = EventSubscription.query.get_or_404(subscription_id)
    now = datetime.now()
    # Определяем время окончания мероприятия
    try:
        hours, minutes = map(int, sub.event.duration.split(':'))
        event_end = sub.event.date + timedelta(hours=hours, minutes=minutes)
    except Exception:
        event_end = sub.event.date
    if not (sub.event.date <= now < event_end):
        flash("Нельзя обновить статус для данного мероприятия, так как оно не идёт в данный момент.", "error")
        return redirect(url_for('moderator_participant_detail', user_id=sub.user_id))
    new_status = request.form.get('status')
    if new_status not in ['visited', 'no_show']:
        flash("Неверный статус.", "error")
        return redirect(url_for('moderator_participant_detail', user_id=sub.user_id))
    sub.status = new_status
    db.session.commit()
    flash("Статус обновлён.", "success")
    return redirect(url_for('moderator_participant_detail', user_id=sub.user_id))


@app.route('/moderator/participants/<int:user_id>/edit', methods=['GET', 'POST'])
@limiter.exempt
def edit_participant(user_id):
    # только модератор
    if session.get('user_role') != 'moderator':
        abort(403)
    participant = User.query.get_or_404(user_id)

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'profile':
            # здесь модератор может менять абсолютно всё
            participant.full_name      = request.form.get('full_name')
            participant.username       = request.form.get('username')
            participant.email          = request.form.get('email')
            participant.telegram_login = request.form.get('telegram_login')
            # дата рождения в формате YYYY-MM-DD
            dob = request.form.get('date_of_birth')
            if dob:
                participant.date_of_birth = datetime.strptime(dob, '%Y-%m-%d').date()
            participant.phone_number   = request.form.get('phone_number')
            participant.about_me       = request.form.get('about_me')
            participant.gender         = request.form.get('gender')
            participant.skills         = request.form.get('skills')
            db.session.commit()
            flash('Данные участника обновлены.', 'success')
            return redirect(url_for('edit_participant', user_id=user_id))

        elif form_type == 'password':
            new_pw  = request.form.get('new_password')
            conf_pw = request.form.get('confirm_password')
            if not new_pw or new_pw != conf_pw:
                flash('Пароли не совпадают.', 'error')
            else:
                participant.set_password(new_pw)
                db.session.commit()
                flash('Пароль участника успешно изменён.', 'success')
            return redirect(url_for('edit_participant', user_id=user_id))

    # GET — рисуем форму, передаём флаг, что это модераторский просмотр
    return render_template(
        'participant_profile.html',
        user=participant,
        is_moderator=True
    )



@app.route('/moderator/organizers/approved')
@limiter.exempt
def approved_organizers():
    if session.get('user_role') != 'moderator':
        abort(403)
    organizers   = User.query.filter_by(role='organizer', org_approved=True).all()
    event_spheres = EventSphere.query.all()
    return render_template('dashboard_organizer_list.html',
                           organizers=organizers,
                           event_spheres=event_spheres)

@app.route('/moderator/organizers/<int:user_id>/edit', methods=['GET','POST'])
@limiter.exempt
def edit_organizer(user_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    org = User.query.get_or_404(user_id)
    if org.role != 'organizer':
        abort(400)

    if request.method == 'POST':
        form_type = request.form.get('form_type')
        if form_type == 'profile':
            org.org_name        = request.form.get('org_name')
            org.email           = request.form.get('email')
            org.org_description = request.form.get('org_description')
            org.org_sphere      = request.form.get('org_sphere')
            org.org_phone       = request.form.get('org_phone')

            file = request.files.get('accreditation_image')
            if file:
                fn = secure_filename(file.filename)
                folder = current_app.config['UPLOAD_FOLDER']
                os.makedirs(folder, exist_ok=True)
                file.save(os.path.join(folder, fn))
                org.accreditation_image = fn

            db.session.commit()
            flash('Данные организатора обновлены.', 'success')
            return redirect(url_for('edit_organizer', user_id=user_id))

        elif form_type == 'password':
            new_pw  = request.form.get('new_password')
            conf_pw = request.form.get('confirm_password')
            if not new_pw or new_pw != conf_pw:
                flash('Пароли не совпадают.', 'error')
            else:
                org.set_password(new_pw)
                db.session.commit()
                flash('Пароль организатора изменён.', 'success')
            return redirect(url_for('edit_organizer', user_id=user_id))

    return render_template(
        'organizer_profile.html',
        user=org,
        is_moderator=True,
        accreditation_url=url_for('view_accreditation', user_id=org.id)
    )

@app.route('/moderator/create_moderator', methods=['POST'])
@limiter.exempt
def create_moderator():
    if session.get('user_role') != 'moderator':
        abort(403)
    username = request.form['username'].strip()
    email    = request.form['email'].strip()
    password = request.form['password']
    error = None
    if not username or not email or not password:
        error = "Все поля обязательны."
    elif User.query.filter_by(username=username).first():
        error = "Имя пользователя занято."
    elif User.query.filter_by(email=email).first():
        error = "Email уже используется."
    if error:
        flash(error, 'error')
        return redirect(url_for('dashboard'))
    new_mod = User(username=username, email=email, role='moderator')
    new_mod.set_password(password)
    db.session.add(new_mod)
    db.session.commit()
    flash('Новый модератор создан.', 'success')
    return redirect(url_for('dashboard'))


# --- Подписка на мероприятие + обновление subscription_count ---
@app.route('/subscribe/<int:event_id>', methods=['POST'])
@limiter.exempt
def subscribe(event_id):
    # только для участников
    if 'user_id' not in session or session.get('user_role') != 'participant':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Функция доступна только для участников."), 403
        flash("Функция доступна только для участников.", "error")
        return redirect(url_for('login'))

    event = Event.query.get_or_404(event_id)
    now = datetime.now()
    if event.date < now:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Нельзя записаться на прошедшее мероприятие."), 400
        flash("Нельзя записаться на прошедшее мероприятие.", "error")
        return redirect(request.referrer or url_for('index'))

    uid = session['user_id']
    # уже подписан?
    existing = EventSubscription.query.filter_by(event_id=event_id, user_id=uid).first()
    if existing:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Вы уже записаны на это мероприятие.", event_id=event_id, subscribed=True)
        flash("Вы уже записаны на это мероприятие.", "info")
        return redirect(request.referrer or url_for('index'))

    # создаём подписку
    sub = EventSubscription(event_id=event_id, user_id=uid, status='registered')
    db.session.add(sub)

    # обновляем кэш подписок
    event.subscription_count = (event.subscription_count or 0) + 1

    db.session.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True, message="Вы успешно записались на мероприятие.", event_id=event_id, subscribed=True)
    flash("Вы успешно записались на мероприятие.", "success")
    return redirect(request.referrer or url_for('index'))



# --- Отписка от мероприятия + обновление subscription_count ---
@app.route('/unsubscribe/<int:event_id>', methods=['POST'])
@limiter.exempt
def unsubscribe(event_id):
    # только для участников
    if 'user_id' not in session or session.get('user_role') != 'participant':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Функция доступна только для участников."), 403
        flash("Функция доступна только для участников.", "error")
        return redirect(url_for('login'))

    uid = session['user_id']
    sub = EventSubscription.query.filter_by(event_id=event_id, user_id=uid).first()
    if sub:
        db.session.delete(sub)
        # декрементим кэш
        event = Event.query.get_or_404(event_id)
        event.subscription_count = max((event.subscription_count or 1) - 1, 0)
        db.session.commit()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=True, message="Вы отписались от мероприятия.", event_id=event_id, subscribed=False)
        flash("Вы отписались от мероприятия.", "success")
    else:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Вы не были записаны на это мероприятие.", event_id=event_id, subscribed=False)
        flash("Вы не были записаны на это мероприятие.", "info")

    return redirect(request.referrer or url_for('index'))






@app.route('/my_events')
@limiter.exempt
def my_events():
    if 'user_id' not in session or session.get('user_role') != 'participant':
        flash("Данная функция доступна только для участников.", "error")
        return redirect(url_for('login'))
    user = User.query.get(session['user_id'])
    now = datetime.now()
    updated = False

    for sub in user.subscriptions:
        # вычисляем дату окончания с учётом продолжительности в формате "HH:MM"
        try:
            h, m = map(int, sub.event.duration.split(':'))
            duration_td = timedelta(hours=h, minutes=m)
        except Exception:
            duration_td = timedelta(0)
        event_end = sub.event.date + duration_td

        # обновляем только если текущий статус — зарегистрирован или проходит
        if sub.status in ('registered', 'in_progress'):
            if now < sub.event.date:
                new_status = 'registered'
            elif sub.event.date <= now < event_end:
                new_status = 'in_progress'
            else:  # now >= event_end
                new_status = 'no_show'

            if sub.status != new_status:
                sub.status = new_status
                updated = True

    if updated:
        db.session.commit()

    return render_template('my_events.html', subscriptions=user.subscriptions, now=now)


@app.route('/delete_subscription/<int:event_id>', methods=['POST'])
@limiter.exempt
def delete_subscription(event_id):
    if 'user_id' not in session or session.get('user_role') != 'participant':
        flash("Функция доступна только для участников.", "error")
        return redirect(url_for('login'))
    sub = EventSubscription.query.filter_by(event_id=event_id, user_id=session['user_id']).first()
    if sub:
        db.session.delete(sub)
        db.session.commit()
        flash("Подписка удалена.", "success")
    else:
        flash("Вы не были записаны на это мероприятие.", "info")
    return redirect(url_for('my_events'))



@app.route('/participants/search')
@limiter.exempt
def participants_search():
    if session.get('user_role') != 'participant':
        abort(403)
    q = request.args.get('q', '').strip()
    query = User.query.filter_by(role='participant') \
                      .filter(User.id != session['user_id'])
    if q:
        il = f"%{q}%"
        query = query.filter(
            or_(
                User.username.ilike(il),
                User.email.ilike(il)
            )
        )
    users = query.all()

    result = []
    for u in users:
        fr = Friendship.query.filter(
            or_(
                and_(Friendship.requester_id==session['user_id'],
                     Friendship.receiver_id==u.id),
                and_(Friendship.requester_id==u.id,
                     Friendship.receiver_id==session['user_id'])
            )
        ).first()
        result.append({
            'id': u.id,
            'username': u.username,
            'email': u.email,
            'friendship': fr.status if fr else 'none'
        })
    return jsonify(result)


@app.route('/friends/send_request/<int:user_id>', methods=['POST'])
@limiter.exempt
def send_friend_request(user_id):
    if session.get('user_role') != 'participant':
        abort(403)
    if user_id == session['user_id']:
        return jsonify(success=False), 400

    fr = Friendship.query.filter(
        or_(
            and_(Friendship.requester_id==session['user_id'],
                 Friendship.receiver_id==user_id),
            and_(Friendship.requester_id==user_id,
                 Friendship.receiver_id==session['user_id'])
        )
    ).first()

    if not fr:
        # новый запрос
        fr = Friendship(
            requester_id=session['user_id'],
            receiver_id=user_id,
            status='pending'
        )
        db.session.add(fr)
    else:
        # уже был запрос или дружба
        if fr.status == 'rejected':
            # повторяем запрос
            fr.status = 'pending'
            fr.created_at = datetime.now()
        # если pending или accepted — ничего не делаем

    db.session.commit()


    requester = User.query.get(session['user_id'])
    note = Notification(
        user_id=user_id,
        message=f"У вас новое приглашение в друзья от {requester.username}.",
        url=url_for('dashboard', _external=False) + "?open=friends"
    )
    db.session.add(note)
    db.session.commit()

    return jsonify(success=True)

@app.route('/friends/respond/<int:friendship_id>', methods=['POST'])
@limiter.exempt
def respond_friend_request(friendship_id):
    if session.get('user_role') != 'participant':
        abort(403)
    fr = Friendship.query.get_or_404(friendship_id)
    if fr.receiver_id != session['user_id']:
        abort(403)
    action = request.form.get('action')
    if action == 'accept':
        fr.status = 'accepted'
    elif action == 'reject':
        fr.status = 'rejected'
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for('dashboard'))

# Детали друга и его мероприятия
@app.route('/friends/<int:user_id>')
@limiter.exempt
def friend_detail(user_id):
    if session.get('user_role') != 'participant':
        abort(403)
    # проверяем, что есть дружба принятая
    fr = Friendship.query.filter(
        or_(
            and_(Friendship.requester_id==session['user_id'], Friendship.receiver_id==user_id),
            and_(Friendship.requester_id==user_id,  Friendship.receiver_id==session['user_id'])
        ),
        Friendship.status=='accepted'
    ).first()
    if not fr:
        abort(403)
    friend = User.query.get_or_404(user_id)
    # собираем подписки друга
    subs = []
    now = datetime.now()
    for sub in friend.subscriptions:
        # учитываем приватность друга
        if friend.event_privacy == 'private':
            continue
        if friend.event_privacy == 'friends' and not fr:
            continue
        # выстроим словарь для шаблона
        subs.append({
            'event': sub.event,
            'status': sub.status
        })
    return render_template('friend_detail.html', friend=friend, subscriptions=subs)

# Настройка приватности
@app.route('/friends/privacy', methods=['POST'])
@limiter.exempt
def set_privacy():
    if session.get('user_role') != 'participant':
        abort(403)
    val = request.form.get('privacy')
    if val in ['public','friends','private']:
        user = User.query.get(session['user_id'])
        user.event_privacy = val
        db.session.commit()
    return redirect(url_for('dashboard'))


# Получить список уведомлений для текущего пользователя
@app.route('/notifications')
@limiter.exempt
def get_notifications():
    uid = session.get('user_id')
    if not uid:
        return jsonify([])

    role = session.get('user_role')

    # Для участника: напоминание за день до зарегистрированного события
    if role == 'participant':
        now = datetime.now()
        tomorrow = now.date() + timedelta(days=1)

        # Берём подписки со статусом 'registered'
        subs = EventSubscription.query.filter_by(user_id=uid, status='registered').all()
        for sub in subs:
            ev = sub.event
            # Если дата события — завтра
            if ev.date and ev.date.date() == tomorrow:
                message = f"Мероприятие «{ev.title}» начнётся завтра."
                link    = url_for('view_event', event_id=ev.id)

                # Чтобы не дублировать уведомления
                exists = Notification.query.filter_by(
                    user_id=uid,
                    message=message,
                    url=link
                ).first()
                if not exists:
                    n = Notification(user_id=uid, message=message, url=link)
                    db.session.add(n)
        db.session.commit()

    # Получаем все уведомления (и для участников, и для модераторов)
    notes = (
        Notification.query
        .filter_by(user_id=uid)
        .order_by(Notification.created_at.desc())
        .all()
    )

    # Формируем JSON‑ответ, включая ссылку
    return jsonify([
        {
            'id':         n.id,
            'message':    n.message,
            'url':        n.url or '',
            'created_at': n.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for n in notes
    ])


@app.route('/notifications/<int:notification_id>', methods=['DELETE'])
@limiter.exempt
def delete_notification(notification_id):
    uid = session.get('user_id')
    if not uid:
        return jsonify(success=False), 403
    n = Notification.query.get_or_404(notification_id)
    if n.user_id != uid:
        return jsonify(success=False), 403
    db.session.delete(n)
    db.session.commit()
    return jsonify(success=True)

@app.route('/notifications/clear_all', methods=['DELETE'])
def clear_notifications():
    uid = session.get('user_id')
    if not uid:
        return jsonify(success=False), 403
    # Удаляем все уведомления текущего пользователя
    Notification.query.filter_by(user_id=uid).delete()
    db.session.commit()
    return jsonify(success=True)


# СПИСОК ОРГАНИЗАТОРОВ для участников
@app.route('/participant/organizers')
@limiter.exempt
def participant_organizers():
    if session.get('user_role') != 'participant':
        abort(403)
    organizers = User.query.filter_by(role='organizer', org_approved=True).all()
    # передаём подписки текущего пользователя
    subs = { sub.organizer_id for sub in User.query.get(session['user_id']).organizer_subscriptions }
    return render_template('participant_organizers.html', organizers=organizers, subs=subs)

# --- Просмотр карточки организатора + инкремент view_count ---
@app.route('/participant/organizers/<int:user_id>')
@limiter.exempt
def view_organizer(user_id):
    organizer = User.query.filter_by(
        id=user_id, role='organizer', org_approved=True
    ).first_or_404()

    uid = session.get('user_id')
    if uid:
        viewer = User.query.get(uid)
        if viewer and viewer.role == 'participant':
            organizer.view_count = (organizer.view_count or 0) + 1
            db.session.commit()

    # События организатора
    events = Event.query.filter_by(
        creator_id=organizer.id, is_approved=True
    ).order_by(Event.date).all()

    # Подписка на организатора
    is_subscribed = False
    if uid:
        is_subscribed = bool(OrganizerSubscription.query.filter_by(
            user_id=uid, organizer_id=organizer.id
        ).first())

    return render_template(
        'participant_organizer_detail.html',
        organizer=organizer,
        events=events,
        is_subscribed=is_subscribed
    )

# ПОДПИСАТЬСЯ
@app.route('/participant/organizers/<int:org_id>/subscribe', methods=['POST'])
@limiter.exempt
def participant_subscribe_org(org_id):
    if session.get('user_role') != 'participant':
        abort(403)

    user = User.query.get(session['user_id'])
    org  = User.query.filter_by(id=org_id, role='organizer').first_or_404()

    exists = OrganizerSubscription.query.filter_by(
        user_id=user.id, organizer_id=org.id
    ).first()
    if not exists:
        sub = OrganizerSubscription(user_id=user.id,
                                    organizer_id=org.id)
        db.session.add(sub)
        db.session.commit()

        # --- Уведомляем в Telegram ---
        if user.telegram_id:
            base = request.url_root.rstrip('/')
            link = f"{base}/participant/organizers"
            text = (
                f"✅ Вы подписались на мероприятия организатора «{org.org_name}».\n\n"
                f"Смотреть список: {link}"
            )
            send_message(int(user.telegram_id), text)

        return jsonify(success=True,
                       notify=True,
                       notify_text="В Telegram отправлено уведомление.")
    else:
        return jsonify(success=False, notify=False), 200


@app.route('/participant/organizers/<int:org_id>/unsubscribe', methods=['POST'])
@limiter.exempt
def participant_unsubscribe_org(org_id):
    if session.get('user_role') != 'participant':
        abort(403)

    user = User.query.get(session['user_id'])
    sub  = OrganizerSubscription.query.filter_by(
        user_id=user.id, organizer_id=org_id
    ).first()

    if sub:
        # Сохраняем имя организатора до удаления
        org_name = sub.organizer.org_name if sub.organizer else ''

        db.session.delete(sub)
        db.session.commit()

        # Теперь можно спокойно уведомлять
        if user.telegram_id:
            text = f"ℹ️ Вы отписались от мероприятий организатора «{org_name}»."
            send_message(int(user.telegram_id), text)

        return jsonify(success=True, notify=False)
    else:
        return jsonify(success=False, notify=False), 200


@app.route('/events/<int:event_id>/review', methods=['GET', 'POST'])
@limiter.exempt
def leave_review(event_id):
    # доступ только для участника, который посетил мероприятие
    if session.get('user_role') != 'participant':
        abort(403)
    user = User.query.get(session['user_id'])
    # проверяем, что у него есть подписка и статус 'visited'
    sub = EventSubscription.query.filter_by(
        user_id=user.id, event_id=event_id, status='visited'
    ).first()
    if not sub:
        flash("Оставить отзыв можно только после посещения мероприятия.", "error")
        return redirect(url_for('my_events'))

    event = Event.query.get_or_404(event_id)

    if request.method == 'POST':
        rating  = int(request.form.get('rating', 0))
        comment = request.form.get('comment', '').strip()
        if not (1 <= rating <= 10) or not comment:
            flash("Нужно поставить оценку от 1 до 10 и написать комментарий.", "error")
            return redirect(url_for('leave_review', event_id=event_id))

        filename = None
        file = request.files.get('image')
        if file and allowed_file(file.filename):
            # формируем безопасное имя
            filename = secure_filename(f"{user.id}_{event_id}_{file.filename}")
            # сохраняем в папку uploads/reviews
            save_path = os.path.join(current_app.config['REVIEW_DIR'], filename)
            file.save(save_path)

        review = Review(
            user_id=user.id,
            event_id=event_id,
            rating=rating,
            comment=comment,
            image_filename=filename,
            is_approved=False
        )
        db.session.add(review)
        db.session.commit()
        flash("Спасибо! Ваш отзыв отправлен на модерацию.", "success")
        return redirect(url_for('my_events'))

    return render_template('leave_review.html', event=event)

@app.route('/moderator/reviews')
@limiter.exempt
def moderator_reviews():
    if session.get('user_role') != 'moderator':
        abort(403)
    pending = Review.query.filter_by(is_approved=False).order_by(Review.created_at.desc()).all()
    return render_template('moderator_reviews.html', reviews=pending)

@app.route('/moderator/reviews/<int:review_id>/approve', methods=['POST'])
@limiter.exempt
def approve_review(review_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    rev = Review.query.get_or_404(review_id)
    rev.is_approved = True
    db.session.commit()
    flash("Отзыв одобрен.", "success")
    return redirect(url_for('moderator_reviews'))

@app.route('/moderator/reviews/<int:review_id>/delete', methods=['POST'])
@limiter.exempt
def delete_review(review_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    rev = Review.query.get_or_404(review_id)
    # удалить файл, если есть
    if rev.image_filename:
        try:
            os.remove(os.path.join(UPLOAD_FOLDER, rev.image_filename))
        except:
            pass
    db.session.delete(rev)
    db.session.commit()
    flash("Отзыв удалён.", "info")
    return redirect(url_for('moderator_reviews'))

# 1) Основной роут — показывает и новые, и одобренные
@app.route('/organizer/reviews')
@limiter.exempt
def organizer_reviews():
    if session.get('user_role') != 'organizer':
        abort(403)

    # все отзывы к событиям этого организатора, разделяем по флагу is_approved
    pending_reviews = (
        Review.query
              .join(Event)
              .filter(Event.creator_id == session['user_id'],
                      Review.is_approved == False)
              .order_by(Review.created_at.desc())
              .all()
    )
    approved_reviews = (
        Review.query
              .join(Event)
              .filter(Event.creator_id == session['user_id'],
                      Review.is_approved == True)
              .order_by(Review.created_at.desc())
              .all()
    )

    return render_template(
        'organizer_reviews.html',
        pending_reviews=pending_reviews,
        approved_reviews=approved_reviews
    )


# 2) Одобрение конкретного отзыва
@app.route('/organizer/reviews/<int:review_id>/approve', methods=['POST'])
@limiter.exempt
def organizer_approve_review(review_id):
    if session.get('user_role') != 'organizer':
        abort(403)

    rev = Review.query.get_or_404(review_id)
    # проверяем, что отзыв действительно на одном из наших событий
    if rev.event.creator_id != session['user_id']:
        abort(403)

    rev.is_approved = True
    db.session.commit()
    flash("Отзыв одобрен.", "success")

    # возвращаемся на общий список
    return redirect(url_for('organizer_reviews'))


# 3) Отклонение (удаление) конкретного отзыва
@app.route('/organizer/reviews/<int:review_id>/delete', methods=['POST'])
@limiter.exempt
def organizer_delete_review(review_id):
    if session.get('user_role') != 'organizer':
        abort(403)

    rev = Review.query.get_or_404(review_id)
    # снова проверка по владельцу события
    if rev.event.creator_id != session['user_id']:
        abort(403)

    # при необходимости удалить файл картинки
    if rev.image_filename:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER_REVIEWS'], rev.image_filename))
        except OSError:
            pass

    db.session.delete(rev)
    db.session.commit()
    flash("Отзыв удалён.", "info")

    return redirect(url_for('organizer_reviews'))


from datetime import datetime

@app.route('/past_events')
@limiter.exempt
def past_events():
    # все одобренные события, дата которых уже прошла
    now = datetime.now()
    past = (
        Event.query
             .filter(Event.is_approved == True, Event.date < now)
             .order_by(Event.date.desc())
             .all()
    )
    return render_template('past_events.html', events=past)



 #Получить существующую персоналию (для предзаполнения формы)
@app.route('/organizer/events/<int:event_id>/personality')
@limiter.exempt
def get_personality(event_id):
    if session.get('user_role') != 'organizer':
        abort(403)
    ev = Event.query.get_or_404(event_id)
    if ev.creator_id != session['user_id']:
        abort(403)
    # берём первую привязанную персоналию (или None)
    p = ev.personalities[0] if ev.personalities else None
    if not p:
        return jsonify(success=False), 404
    return jsonify(success=True, name=p.name, description=p.description)

#  Добавить / обновить персоналию
@app.route('/organizer/events/<int:event_id>/add_personality', methods=['POST'])
@limiter.exempt
def add_personality(event_id):
    if session.get('user_role') != 'organizer':
        abort(403)
    ev = Event.query.get_or_404(event_id)
    if ev.creator_id != session['user_id']:
        abort(403)

    name = request.form.get('name','').strip()
    desc = request.form.get('description','').strip()
    if not name:
        return jsonify(success=False, error="Имя обязательно"), 400

    # либо найти по имени, либо создать
    p = Personality.query.filter_by(name=name).first()
    if not p:
        p = Personality(name=name, description=desc)
    else:
        p.description = desc

    # отвязываем все старые, чтобы была всегда одна
    ev.personalities = [p]

    db.session.add(p)
    db.session.commit()
    return jsonify(success=True, id=p.id, name=p.name, description=p.description)



# Получить статистику по событию в JSON
@app.route('/organizer/events/<int:event_id>/stats.json')
@limiter.exempt
def organizer_event_stats_json(event_id):
    # Доступ только для авторизованного организатора-создателя
    if session.get('user_role') != 'organizer':
        abort(403)
    ev = Event.query.get_or_404(event_id)
    if ev.creator_id != session['user_id']:
        abort(403)

    # 1) Подписки
    total_subs = EventSubscription.query.filter_by(event_id=event_id).count()
    by_status = dict(
        registered   = EventSubscription.query.filter_by(event_id=event_id, status='registered').count(),
        in_progress  = EventSubscription.query.filter_by(event_id=event_id, status='in_progress').count(),
        visited      = EventSubscription.query.filter_by(event_id=event_id, status='visited').count(),
        no_show      = EventSubscription.query.filter_by(event_id=event_id, status='no_show').count()
    )

    # 2) Избранное
    fav_count = Favorite.query.filter_by(fav_type='event', fav_value=str(event_id)).count()

    # 3) Отзывы
    total_reviews    = Review.query.filter_by(event_id=event_id).count()
    pending_reviews  = Review.query.filter_by(event_id=event_id, is_approved=False).count()
    approved_reviews = total_reviews - pending_reviews

    return jsonify({
        'event_id': event_id,
        'subscriptions': {
            'total': total_subs,
            'by_status': by_status
        },
        'favorites': fav_count,
        'reviews': {
            'total': total_reviews,
            'approved': approved_reviews,
            'pending': pending_reviews
        }
    })

# Страница/шаблон со статистикой (если потребуется)
@app.route('/organizer/events/<int:event_id>/stats')
@limiter.exempt
def organizer_event_stats(event_id):
    # просто рендерим пустой контейнер, всё подтянет JS
    if session.get('user_role') != 'organizer':
        abort(403)
    ev = Event.query.get_or_404(event_id)
    if ev.creator_id != session['user_id']:
        abort(403)
    return render_template('organizer_event_stats.html', event=ev)



from flask import render_template, abort, session
from app.models import Event, User, EventSubscription, Favorite, Review
from datetime import datetime

@app.route('/analytics')
@limiter.exempt
def analytics():
    role = session.get('user_role')
    if role not in ['organizer', 'moderator']:
        abort(403)

    # Статусы подписки, которые у нас есть
    STATUSES = ['registered', 'in_progress', 'visited', 'no_show']

    # Берём либо все события/организаторов (для модератора), либо только свои (для организатора)
    if role == 'moderator':
        events = Event.query.order_by(Event.date).all()
        organizers = User.query.filter_by(role='organizer').all()
    else:
        uid = session['user_id']
        events = Event.query.filter_by(creator_id=uid).order_by(Event.date).all()
        organizers = [User.query.get(uid)]

    # Формируем данные по событиям
    analytics_events = []
    for ev in events:
        # Подсчёт подписок по статусам
        by_status = {
            status: EventSubscription.query
                        .filter_by(event_id=ev.id, status=status)
                        .count()
            for status in STATUSES
        }
        total_subs = sum(by_status.values())

        # Избранное
        fav_count = Favorite.query \
            .filter_by(fav_type='event', fav_value=str(ev.id)) \
            .count()

        # Отзывы
        total_reviews   = Review.query.filter_by(event_id=ev.id).count()
        pending_reviews = Review.query.filter_by(event_id=ev.id, is_approved=False).count()
        approved_reviews = total_reviews - pending_reviews

        analytics_events.append({
            'id': ev.id,
            'title': ev.title,
            'date': ev.date,
            'view_count': ev.view_count or 0,
            'registered':  by_status['registered'],
            'in_progress': by_status['in_progress'],
            'visited':     by_status['visited'],
            'no_show':     by_status['no_show'],
            'subscription_count': total_subs,
            'favorite_count':     fav_count,
            'total_reviews':      total_reviews,
            'approved_reviews':   approved_reviews,
            'pending_reviews':    pending_reviews
        })

    # Формируем данные по организаторам
    analytics_orgs = []
    for org in organizers:
        # События, которые они создали
        evs = Event.query.filter_by(creator_id=org.id, is_approved=True).all()

        # Вместо суммирования просмотров событий берём просмотры карточки организатора
        profile_views = org.view_count or 0

        # Всего подписок на все их события
        total_subscriptions = sum(
            EventSubscription.query.filter_by(event_id=e.id).count()
            for e in evs
        )

        # Всего добавили в избранное все их события
        total_favorites = sum(
            Favorite.query.filter_by(fav_type='event', fav_value=str(e.id)).count()
            for e in evs
        )

        # Отзывы по всем их событиям
        total_reviews   = sum(Review.query.filter_by(event_id=e.id).count() for e in evs)
        pending_reviews = sum(Review.query.filter_by(event_id=e.id, is_approved=False).count() for e in evs)
        approved_reviews = total_reviews - pending_reviews

        analytics_orgs.append({
            'id': org.id,
            'name': org.org_name or org.username,
            'events_created':      len(evs),
            'total_views':         profile_views,
            'total_subscriptions': total_subscriptions,
            'total_favorites':     total_favorites,
            'total_reviews':       total_reviews,
            'approved_reviews':    approved_reviews,
            'pending_reviews':     pending_reviews
        })

    return render_template(
        'analytics.html',
        analytics_events=analytics_events,
        analytics_orgs=analytics_orgs,
        is_moderator=(role == 'moderator')
    )

@app.route('/dashboard/recommendations')
@limiter.exempt
def dashboard_recommendations():
    if not g.user or g.user.role != 'participant':
        abort(403)

    # Берём рекоммендации
    recs = UserRecommendation.query \
             .filter_by(user_id=g.user.id) \
             .order_by(UserRecommendation.created_at.desc()) \
             .all()

    # Если ещё нет — генерируем
    if not recs:
        generate_recommendations_for_user(g.user)
        recs = UserRecommendation.query \
                 .filter_by(user_id=g.user.id) \
                 .order_by(UserRecommendation.created_at.desc()) \
                 .all()

    # Подписки пользователя для быстрых проверок
    user_sub_ids = { sub.event_id for sub in g.user.subscriptions }

    now = datetime.now()
    for rec in recs:
        ev = rec.event
        # вычисляем конец мероприятия
        try:
            h, m = map(int, ev.duration.split(':'))
            event_end = ev.date + timedelta(hours=h, minutes=m)
        except:
            event_end = ev.date

        # статус
        if now < ev.date:
            status = 'предстоит'
        elif ev.date <= now < event_end:
            status = 'проходит'
        else:
            status = 'прошло'
        ev.filtered_status = status

        # подписан?
        ev.subscribed = (ev.id in user_sub_ids)

    return render_template(
        'dashboard_recommendations.html',
        recommendations=recs
    )



@app.route('/moderator/participants/<int:user_id>/block', methods=['POST'])
@limiter.exempt
def block_participant(user_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    user = User.query.get_or_404(user_id)
    reason = request.form.get('reason', '').strip()
    if not reason:
        flash('Нужно указать причину блокировки', 'error')
        return redirect(url_for('moderator_participant_detail', user_id=user_id))

    user.is_blocked = True
    user.block_reason = reason
    db.session.commit()

    # уведомляем через Telegram, если привязан
    if user.telegram_id:
        send_message(int(user.telegram_id),
                     f"❌ Ваш аккаунт был заблокирован.\nПричина: {reason}")

    flash(f"Пользователь {user.username} заблокирован.", 'success')
    return redirect(url_for('moderator_participants'))


@app.route('/moderator/participants/<int:user_id>/unblock', methods=['POST'])
@limiter.exempt
def unblock_participant(user_id):
    if session.get('user_role') != 'moderator':
        abort(403)
    user = User.query.get_or_404(user_id)

    user.is_blocked = False
    user.block_reason = ''
    db.session.commit()

    # уведомляем через Telegram, если привязан
    if user.telegram_id:
        send_message(
            int(user.telegram_id),
            "✅ Ваш аккаунт был разблокирован. Пожалуйста, войдите снова."
        )

    flash(f"Пользователь {user.username} разблокирован.", 'success')
    return redirect(url_for('moderator_participants'))


@app.before_request
@limiter.exempt
def enforce_block():
    from app.models import User
    # если пользователь залогинен, но заблокирован — выкинуть
    if 'user_id' in session:
        u = User.query.get(session['user_id'])
        if u and u.is_blocked:
            reason = u.block_reason or 'без причины'
            session.clear()
            flash(f"Ваш аккаунт заблокирован: {reason}", 'error')
            return redirect(url_for('login'))


from flask import send_from_directory

@app.route('/uploads/meropimage/<filename>')
@limiter.exempt
def uploaded_event_image(filename):
    # отдаем файл из папки uploads/meropimage
    return send_from_directory(app.config['MEROP_IMAGE_FOLDER'], filename)

@app.route('/uploads/reviews/<filename>')
@limiter.exempt
def uploaded_review_image(filename):
    return send_from_directory(current_app.config['REVIEW_DIR'], filename)
