# models.py
from app.app import db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = 'users'
    id                 = db.Column(db.Integer, primary_key=True)
    telegram_id        = db.Column(db.BigInteger, unique=True, nullable=True)
    username           = db.Column(db.String(50), unique=True, nullable=False)
    email              = db.Column(db.String(120), unique=True, nullable=False)
    password_hash      = db.Column(db.String(256), nullable=False)
    role               = db.Column(db.String(20), nullable=False, default='participant')
    full_name          = db.Column(db.String(100))
    org_name           = db.Column(db.String(100))
    org_description    = db.Column(db.Text)
    org_sphere         = db.Column(db.String(100))
    org_phone          = db.Column(db.String(20))
    accreditation_image= db.Column(db.String(200))
    org_approved       = db.Column(db.Boolean, default=False)
    event_privacy      = db.Column(db.String(20), nullable=False, default='public')
    telegram_login     = db.Column(db.String(64))
    date_of_birth      = db.Column(db.Date)      # YYYY-MM-DD
    phone_number       = db.Column(db.String(20))
    about_me           = db.Column(db.Text)
    gender             = db.Column(db.String(10))  # 'male' или 'female'
    skills             = db.Column(db.String(200))
    view_count         = db.Column(db.Integer, default=0)  # новых просмотров карточки организатора
    email_2fa_enabled = db.Column(db.Boolean, default=False, nullable=False)

    region = db.Column(db.String(100))  # регион пользователя
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)
    block_reason = db.Column(db.Text, default='', nullable=True)
    # Отношения
    favorites          = db.relationship('Favorite', backref='user', lazy=True)
    events             = db.relationship('Event', backref='creator', lazy=True)
    subscriptions      = db.relationship(
                            'EventSubscription',
                            back_populates='participant',
                            lazy=True
                         )
    notifications      = db.relationship('Notification', backref='user', lazy=True)
    organizer_subscriptions = db.relationship(
                            'OrganizerSubscription',
                            foreign_keys='OrganizerSubscription.user_id',
                            back_populates='subscriber',
                            lazy=True
                         )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Связующая таблица «многие-ко-многим» между событиями и персоналиями
event_personalities = db.Table(
    'event_personalities',
    db.Column('event_id',       db.Integer, db.ForeignKey('events.id'),        primary_key=True),
    db.Column('personality_id', db.Integer, db.ForeignKey('personalities.id'),  primary_key=True)
)

class UserRecommendation(db.Model):
    __tablename__ = 'user_recommendations'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # Здесь включаем ondelete='CASCADE'
    event_id   = db.Column(
                    db.Integer,
                    db.ForeignKey('events.id', ondelete='CASCADE'),
                    nullable=False
                 )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    user = db.relationship('User', backref=db.backref('recommendations', lazy='dynamic'))
    event = db.relationship(
        'Event',
        backref=db.backref(
            'recommendations',
            cascade='all, delete-orphan',
            passive_deletes=True
        )
    )


def __repr__(self):
        return f"<UserRecommendation user:{self.user_id} event:{self.event_id}>"

class Event(db.Model):
    __tablename__ = 'events'

    id            = db.Column(db.Integer, primary_key=True)
    title         = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text, nullable=False)
    date          = db.Column(db.DateTime, nullable=False)
    address       = db.Column(db.String(200))
    city          = db.Column(db.String(100))
    lat           = db.Column(db.Float)
    lon           = db.Column(db.Float)
    event_format  = db.Column(db.String(20))   # "online" или "offline"
    event_sphere  = db.Column(db.String(200))
    duration      = db.Column(db.String(50))
    event_type    = db.Column(db.String(50))
    tags          = db.Column(db.String(200))
    resources     = db.Column(db.Text)
    is_approved   = db.Column(db.Boolean, default=False)
    creator_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    view_count    = db.Column(db.Integer, default=0)  # просмотры страницы события
    subscription_count = db.Column(db.Integer, default=0)  # «Я приду»
    favorite_count = db.Column(db.Integer, default=0)  # добавлено в избранное
    image_filename      = db.Column(db.String(200), nullable=True)
    priority = db.Column(db.Integer, nullable=False, default=0)
    # связи
    # убираем старый backref и объявляем reviews с cascade/passive_deletes
    reviews = db.relationship(
        'Review',
        back_populates='event',
        cascade='all, delete-orphan',
        passive_deletes=True
    )
    subscriptions = db.relationship('EventSubscription', back_populates='event')
    personalities = db.relationship(
        'Personality',
        secondary=event_personalities,
        back_populates='events'
    )

    def __repr__(self):
        return f"<Event {self.title}>"

class Personality(db.Model):
    __tablename__ = 'personalities'

    id          = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)  # Описание от организатора
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    events = db.relationship(
                 'Event',
                 secondary=event_personalities,
                 back_populates='personalities'
             )

    def __repr__(self):
        return f"<Personality {self.name}>"

class EventSubscription(db.Model):
    __tablename__ = 'event_subscriptions'
    id            = db.Column(db.Integer, primary_key=True)
    event_id      = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status        = db.Column(db.String(20), nullable=False, default='registered')
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Двунаправленные связи
    event         = db.relationship(
                        'Event',
                        back_populates='subscriptions'
                    )
    participant   = db.relationship(
                        'User',
                        back_populates='subscriptions'
                    )

    def __repr__(self):
        return f"<EventSubscription user:{self.user_id} event:{self.event_id} status:{self.status}>"


class Friendship(db.Model):
    __tablename__ = 'friendships'
    id           = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    receiver_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    status       = db.Column(db.String(20), nullable=False, default='pending')  # 'pending','accepted','rejected'
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    requester    = db.relationship('User', foreign_keys=[requester_id], backref='sent_requests')
    receiver     = db.relationship('User', foreign_keys=[receiver_id],  backref='received_requests')


class EventType(db.Model):
    __tablename__ = 'event_types'
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

    def __repr__(self):
        return f"<EventType {self.name}>"


class EventSphere(db.Model):
    __tablename__ = 'event_spheres'
    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f"<EventSphere {self.name}>"


class Review(db.Model):
    __tablename__ = 'reviews'
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    event_id       = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    rating         = db.Column(db.Integer, nullable=False)     # оценка от 1 до 10
    comment        = db.Column(db.Text, nullable=False)
    image_filename = db.Column(db.String(200), nullable=True)  # имя загруженного файла
    is_approved    = db.Column(db.Boolean, default=False)      # модерация
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User', backref='reviews')
    event = db.relationship(
        'Event',
        back_populates='reviews'
    )

    def __repr__(self):
        return f"<Review user:{self.user_id} event:{self.event_id}>"


class Favorite(db.Model):
    __tablename__ = 'favorites'
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    fav_type  = db.Column(db.String(20), nullable=False)   # 'event','sphere','type','organizer'
    fav_value = db.Column(db.String(200), nullable=False)  # для event — id, для остальных — имя

    def __repr__(self):
        return f"<Favorite {self.fav_type}:{self.fav_value} for user:{self.user_id}>"


class Notification(db.Model):
    __tablename__ = 'notifications'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message     = db.Column(db.Text, nullable=False)
    url         = db.Column(db.String(200))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Notification to:{self.user_id}>"


class OrganizerSubscription(db.Model):
    __tablename__ = 'organizer_subscriptions'
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    organizer_id  = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    subscriber    = db.relationship(
                        'User',
                        foreign_keys=[user_id],
                        back_populates='organizer_subscriptions'
                    )
    organizer     = db.relationship(
                        'User',
                        foreign_keys=[organizer_id]
                    )

    def __repr__(self):
        return f"<OrganizerSubscription user:{self.user_id} org:{self.organizer_id}>"
