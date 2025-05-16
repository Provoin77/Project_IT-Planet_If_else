import os
import time
import random
from dotenv import load_dotenv
load_dotenv()

if 'TZ' in os.environ:
    time.tzset()

# monkey-patch url_quote для старых версий Werkzeug
import werkzeug.urls
if not hasattr(werkzeug.urls, 'url_quote'):
    def url_quote(s, safe="/"):
        import urllib.parse
        return urllib.parse.quote(s, safe=safe)
    werkzeug.urls.url_quote = url_quote

from flask import Flask, g, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

# 1️⃣ Создаём приложение
app = Flask(__name__, template_folder='templates', static_folder='static')
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Инициализируем Limiter, по умолчанию — по IP пользователя
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]  # опционально: общие лимиты
)

# Пути к папкам с картинками для отзывов и мероприятий
REVIEW_DIR = os.path.join(os.getcwd(), 'uploads', 'reviews')
MEROP_DIR  = os.path.join(os.getcwd(), 'uploads', 'meropimage')
os.makedirs(REVIEW_DIR, exist_ok=True)
os.makedirs(MEROP_DIR, exist_ok=True)

# Список доступных файлов
review_images = [
    fn for fn in os.listdir(REVIEW_DIR)
    if fn.lower().endswith(('.png','jpg','jpeg','gif'))
]
merop_images = [
    fn for fn in os.listdir(MEROP_DIR)
    if fn.lower().endswith(('.png','jpg','jpeg','gif'))
]

# допустимые расширения
ALLOWED_IMG_EXT = {'png', 'jpg', 'jpeg', 'gif'}


#app.config.setdefault('UPLOAD_FOLDER_REVIEWS', 'static/uploads/reviews')
REVIEW_DIR = os.path.join(os.getcwd(), 'uploads', 'reviews')
os.makedirs(REVIEW_DIR, exist_ok=True)

app.config['REVIEW_DIR'] = REVIEW_DIR
# 2️⃣ Конфигурация
app.config['SECRET_KEY']               = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['SQLALCHEMY_DATABASE_URI']  = os.getenv('DATABASE_URL', 'sqlite:///data.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER']            = os.path.join(os.getcwd(), 'static', 'uploads')
app.config['TELEGRAM_BOT_TOKEN']       = os.getenv('TELEGRAM_BOT_TOKEN')
app.config['TELEGRAM_BOT_USERNAME']    = os.getenv('TELEGRAM_BOT_USERNAME')



# мы храним review и merop в uploads/, не в static
app.config['REVIEW_DIR']               = REVIEW_DIR
app.config['MEROP_IMAGE_FOLDER']       = MEROP_DIR
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 3️⃣ Инициализируем SQLAlchemy
db = SQLAlchemy(app)


from flask_mail import Mail

# читаем из окружения (DOTENV уже подключён выше)
app.config['MAIL_SERVER']        = os.getenv('MAIL_SERVER', 'smtp.yandex.ru')
app.config['MAIL_PORT']          = int(os.getenv('MAIL_PORT', 465))
app.config['MAIL_USE_SSL']       = os.getenv('MAIL_USE_SSL', 'True') == 'True'
app.config['MAIL_USERNAME']      = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD']      = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER']= os.getenv('MAIL_USERNAME')
mail = Mail(app)

from app.routes_auth_email import bp as auth_email_bp
app.register_blueprint(auth_email_bp)


# 4️⃣ При подключении к Postgres ставим часовой пояс
@event.listens_for(Engine, "connect")
def set_postgres_timezone(dbapi_conn, connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("SET TIME ZONE 'Europe/Moscow';")
    cur.close()

# 5️⃣ Подгружаем g.user перед каждым запросом
@app.before_request
def load_current_user():
    from app.models import User
    uid = session.get('user_id')
    g.user = User.query.get(uid) if uid else None

# 6️⃣ Регистрируем Telegram-blueprint
from app.auth_telegram import auth_bp
app.register_blueprint(auth_bp)

# 7️⃣ Регистрируем основной routes.py
from app import routes


def init_db():
    """
    Создаёт таблицы и заполняет их, только если БД ещё пуста.
    """
    from sqlalchemy.exc import IntegrityError
    from werkzeug.security import generate_password_hash
    from datetime import datetime, timedelta
    from app.models import User, EventType, EventSphere, Event, EventSubscription, Review, Favorite, Personality

    with app.app_context():
        try:
            db.create_all()
        except IntegrityError:
            # таблицы уже созданы — выходим
            return

        # если есть хотя бы один пользователь — считаем, что сид уже был
        if User.query.first() is not None:
            return

        # — модератор
        admin = User(
            username='admin', email='admin@example.com',
            role='moderator', password_hash=generate_password_hash('admin123')
        )
        db.session.add(admin)

        # — типы и сферы
        default_types   = ["Соревнование", "Конференция", "Выставка", "Экскурсия", "Мастер-класс", "Воркшоп"]
        default_spheres = ["Наука", "Образование", "Информационные технологии", "Спорт", "Искусство", "Культура"]

        # только новые типы (если кто-то уже добавил)
        existing = {t[0] for t in db.session.query(EventType.name).all()}
        for t in default_types:
            if t not in existing:
                db.session.add(EventType(name=t))
        if EventSphere.query.count() == 0:
            for s in default_spheres:
                db.session.add(EventSphere(name=s))
        db.session.commit()

        # — создаём 3 организатора
        o1 = User(
            username='SberMex89',
            email='org1@mail.ru',
            role='organizer',
            org_name='СберМех',
            org_description='ИТ-решения',
            org_sphere='Информационные технологии',
            org_phone='+79220001111',
            org_approved=True,
            password_hash=generate_password_hash('pass3')
        )
        o2 = User(
            username='WebDevOp',
            email='org2@mail.ru',
            role='organizer',
            org_name='Веб-девоп',
            org_description='Веб-технологии',
            org_sphere='Информационные технологии',
            org_phone='+79850002222',
            org_approved=True,
            password_hash=generate_password_hash('pass4')
        )
        o3 = User(
            username='CosmoTech',
            email='org3@mail.ru',
            role='organizer',
            org_name='КосмоТех',
            org_description='Космические технологии',
            org_sphere='Наука',
            org_phone='+79161234567',
            org_approved=True,
            password_hash=generate_password_hash('pass5')
        )
        db.session.add_all([o1, o2, o3])
        db.session.commit()
        orgs = [o1, o2, o3]

        now = datetime.now()
        # фиксированные центры городов
        centers = {
            "Москва": (55.75, 37.61),
            "Санкт-Петербург": (59.93, 30.33),
        }

        # — создаём 20 прошедших мероприятий (≈50% Москва, 50% СПб)
        past_events = []
        names_past = [
            "TechTalk 2023", "Наука рядом", "Молодёжная конференция",
            "AI Summit", "Спортивный форум", "Выставка робототехники",
            "Хакатон Skills", "Экскурсия в планетарий", "Музыкальный фестиваль",
            "Мастер-класс по живописи", "Киберспорт турнир", "Литературный вечер",
            "Образовательный лагерь", "Культура в городе", "BioTech Forum",
            "Startup Meetup", "VR-конференция", "Архитектурная выставка",
            "Спорт-акция", "Экосеминар"
        ]
        for idx, name in enumerate(names_past, start=1):
            # случайный выбор города
            city = "Москва" if random.random() < 0.5 else "Санкт-Петербург"

            # формат события
            fmt = random.choice(['online', 'offline'])

            # если онлайн — ставим точный центр, иначе — рандом вокруг
            if fmt == 'online':
                lat, lon = centers[city]
            else:
                base_lat, base_lon = centers[city]
                lat = base_lat + random.uniform(-0.05, 0.05)
                lon = base_lon + random.uniform(-0.05, 0.05)

            ev = Event(
                title=name,
                description=f"Интересное мероприятие «{name}»",
                date=now - timedelta(days=idx * 2),
                address=f"ул. Примерная, д.{idx}",
                city=city,
                lat=lat,
                lon=lon,
                event_format=fmt,
                duration=f"{random.randint(1, 4):02d}:00",
                event_type=random.choice(default_types),
                event_sphere=random.choice(default_spheres),
                resources="",
                creator_id=random.choice(orgs).id,
                is_approved=True
            )
            # назначаем случайную картинку мероприятия
            if merop_images:
                ev.image_filename = random.choice(merop_images)
            past_events.append(ev)
            db.session.add(ev)
        db.session.commit()

        # — создаём 20 будущих мероприятий (≈50% Москва, 50% СПб)
        upcoming_events = []

        future_names = [
            "Форум инноваций", "Саммит по искусственному интеллекту", "Выставка кибербезопасности",
            "Конференция по возобновляемой энергетике", "Дни цифрового маркетинга", "Шоу виртуальной реальности",
            "Конгресс HealthTech", "Встреча FinTech", "Форум умных городов",
            "Симпозиум EduNext", "Ярмарка робототехники и автоматизации", "Blockchain Connect",
            "Инновации в биотехнологиях", "Лагерь творческого кодинга", "E-commerce Expo",
            "Мастерская дизайн-мышления", "Митап по Data Science", "Саммит Интернета вещей",
            "Форум игровой индустрии", "Ретрит по лидеру и UX"
        ]

        for name in future_names:
            city = "Москва" if random.random() < 0.5 else "Санкт-Петербург"
            fmt = random.choice(['online', 'offline'])

            if fmt == 'online':
                lat, lon = centers[city]
            else:
                base_lat, base_lon = centers[city]
                lat = base_lat + random.uniform(-0.05, 0.05)
                lon = base_lon + random.uniform(-0.05, 0.05)

            ev = Event(
                title=name,
                description=f"Запланированное событие «{name}»",
                date=now + timedelta(days=random.randint(1, 60)),
                address=f"ул. Новый, д.{random.randint(1, 100)}",
                city=city,
                lat=lat,
                lon=lon,
                event_format=fmt,
                duration=f"{random.randint(1, 4):02d}:00",
                event_type=random.choice(default_types),
                event_sphere=random.choice(default_spheres),
                resources="",
                creator_id=random.choice(orgs).id,
                is_approved=True
            )
            # назначаем случайную картинку мероприятия
            if merop_images:
                ev.image_filename = random.choice(merop_images)
            upcoming_events.append(ev)
            db.session.add(ev)

        db.session.commit()

        # — создаём 25 участников с "живыми" именами
        names = [
            "Алексей Иванов", "Мария Петрова", "Иван Сидоров", "Ольга Кузнецова",
            "Дмитрий Смирнов", "Екатерина Попова", "Сергей Лебедев", "Наталья Новикова",
            "Павел Морозов", "Анна Васильева", "Виктор Ковалев", "Ирина Козлова",
            "Никита Дмитриев", "Елена Соколова", "Михаил Орлов", "Татьяна Михайлова",
            "Роман Павлов", "Елена Семёнова", "Вячеслав Степанов", "Оксана Фёдорова",
            "Константин Никитин", "Юлия Захарова", "Григорий Богданов", "Светлана Юрьева",
            "Андрей Ефимов"
        ]
        # Возможные регионы пользователей
        regions = [
            "Москва", "Санкт-Петербург", "Новосибирск",
            "Екатеринбург", "Казань", "Нижний Новгород",
            "Челябинск", "Самара", "Омск", "Ростов-на-Дону"
        ]
        participants = []
        for i, full in enumerate(names, start=1):
            username = full.split()[0].lower() + str(i)
            email = f"email{i}@example.com"
            region = random.choice(regions)
            u = User(
                full_name=full,
                username=username,
                email=email,
                role='participant',
                region=region,
                password_hash=generate_password_hash(f"pass{i}")
            )
            participants.append(u)
            db.session.add(u)
        db.session.commit()
        stars = [
            ("Иван Иванов", "Известный спикер в области ИТ и инноваций"),
            ("Ольга Смирнова", "Эксперт по кибербезопасности с 10-летним опытом"),
            ("Дмитрий Ковалёв", "Пионер в области возобновляемой энергетики"),
            ("Елена Петрова", "Лидер сообщества Data Science в России"),
            ("Александр Орлов", "Гуру UX/UI дизайна и дизайн-мышления"),
        ]

        # Выбираем 2–4 случайных уникальных грядущих мероприятий
        future_seed_events = upcoming_events
        # Если грядущих мероприятий меньше 2, скорректируем границы:
        max_stars = min(len(future_seed_events), 4)
        # Выбираем количество «звёздных» от 2 до max_stars (но не больше количества мероприятий):
        n_stars = random.randint(2, max_stars) if max_stars >= 2 else len(future_seed_events)
        chosen_events = random.sample(future_seed_events, k=n_stars)

        for idx, ev in enumerate(chosen_events):
            name, desc = stars[idx % len(stars)]
            p = Personality(name=name, description=desc)
            db.session.add(p)
            # связываем personality с event
            ev.personalities.append(p)
            app.logger.info(f"[PERSONALITY] Добавлена персоналия «{name}» к событию {ev.id} («{ev.title}»)")

        db.session.commit()
        # — каждому участнику даём в избранном случайные 25% от всех событий
        all_event_ids = [ev.id for ev in past_events + upcoming_events]
        for u in participants:
            # хотя бы один любимый, если событий мало
            k = max(1, int(len(all_event_ids) * 0.25))
            fav_ids = random.sample(all_event_ids, k=k)
            for eid in fav_ids:
                f = Favorite(
                    user_id=u.id,
                    fav_type='event',
                    fav_value=str(eid)  # Favorite.fav_value у вас строка
                )
                db.session.add(f)
        db.session.commit()

        # — подписываем участников на прошлые события (70% visited, 30% no_show)
        for u in participants:
            for ev in past_events:
                if random.random() < 0.6:
                    status = 'visited' if random.random() < 0.7 else 'no_show'
                    sub = EventSubscription(
                        user_id=u.id,
                        event_id=ev.id,
                        status=status,
                        subscribed_at=ev.date - timedelta(days=random.randint(1, 5))
                    )
                    db.session.add(sub)
        db.session.commit()

        # — подключаем участников к будущим событиям просто как зарегистрированных (не посещали)
        for u in participants:
            for ev in upcoming_events:
                if random.random() < 0.3:
                    sub = EventSubscription(
                        user_id=u.id,
                        event_id=ev.id,
                        status='registered',
                        subscribed_at=now
                    )
                    db.session.add(sub)
        db.session.commit()

        # — создаём отзывы для прошедших событий
        comments_approved = [
            "Отличное мероприятие!", "Полезная конференция.", "Не хватило времени.",
            "Превысило все ожидания.", "Очень познавательно."
        ]
        comments_pending = [
            "Будет ли ещё похожее?", "Есть вопросы по докладу.", "Что насчёт записи?"
        ]
        for ev in past_events:
            # от 3 до 6 отзывов на каждое событие
            reviewers = random.sample(participants, k=random.randint(3, 6))
            for u in reviewers:
                rating = random.randint(6, 10)
                comment = random.choice(comments_approved)
                is_approved = random.random() < 0.8
                # часть — сразу на модерацию
                if not is_approved:
                    comment = random.choice(comments_pending)
                rev = Review(
                    user_id=u.id,
                    event_id=ev.id,
                    rating=rating,
                    comment=comment,
                    image_filename=None,
                    is_approved=is_approved,
                    created_at=ev.date + timedelta(hours=random.randint(1, 5))
                )
                if review_images and random.random() < 0.5:
                    fname = random.choice(review_images)
                    rev.image_filename = fname
                db.session.add(rev)
        db.session.commit()

if __name__ == '__main__':
    # при прямом запуске модуля — инициализируем БД, а потом стартуем Flask
    init_db()
    app.run(host='0.0.0.0', port=80)
