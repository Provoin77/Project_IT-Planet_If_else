# app/recommendations.py

from datetime import datetime, timedelta
from sqlalchemy import func, desc
from app.app import db
from app.models import (
    UserRecommendation, Event, EventSubscription, Favorite, User,
    EventType, EventSphere
)
import numpy as np

def generate_recommendations_for_user(user, max_recs=10):
    """
    Улучшенный алгоритм рекомендаций...
    """
    # 1) Удаляем старые рекомендации
    UserRecommendation.query.filter_by(user_id=user.id).delete()
    now = datetime.now()

    # 2) Собираем кандидатов
    candidates = {}
    def add_candidate(eid, score):
        candidates[eid] = max(candidates.get(eid, 0), score)

    # 2.1 Rule-based по организаторам
    org_counts = (
        db.session.query(Event.creator_id, func.count())
        .join(EventSubscription)
        .filter(
            EventSubscription.user_id == user.id,
            EventSubscription.status == 'visited'
        )
        .group_by(Event.creator_id)
        .having(func.count() >= 2)
        .all()
    )
    fav_orgs = {org for org, cnt in org_counts}
    for ev in Event.query.filter(
            Event.creator_id.in_(fav_orgs),
            Event.date > now,
            Event.is_approved
        ).all():
        add_candidate(ev.id, 1.0)

    # 2.2 Rule-based по избранным типам/сферам
    fav_types   = {f.fav_value for f in user.favorites if f.fav_type == 'type'}
    fav_spheres = {f.fav_value for f in user.favorites if f.fav_type == 'sphere'}
    for ev in Event.query.filter(
            Event.date > now,
            Event.is_approved,
            ((Event.event_type.in_(fav_types)) |
             (Event.event_sphere.in_(fav_spheres)))
        ).all():
        add_candidate(ev.id, 0.8)

    # 2.3 Регион
    if user.region:
        for ev in Event.query.filter_by(
                city=user.region,
                is_approved=True
            ).filter(Event.date > now).all():
            add_candidate(ev.id, 0.6)

    # 2.4 Популярные события
    popular = (
        db.session.query(Event.id, func.count().label('cnt'))
        .join(EventSubscription)
        .filter(
            EventSubscription.status == 'registered',
            Event.date > now,
            Event.is_approved
        )
        .group_by(Event.id)
        .order_by(desc('cnt'))
        .limit(20)
        .all()
    )
    for eid, cnt in popular:
        add_candidate(eid, 0.5 + min(cnt, 20)/40)

    # 2.5 Content-based (косинус)
    upcoming = Event.query.filter(Event.date > now, Event.is_approved).all()

    # Сначала заранее грузим полный список типов и сфер из БД
    all_types   = [t.name for t in EventType.query.with_entities(EventType.name).all()]
    all_spheres = [s.name for s in EventSphere.query.with_entities(EventSphere.name).all()]
    feats       = all_types + all_spheres
    idx         = {v: i for i, v in enumerate(feats)}
    dim         = len(feats)

    def vec(event):
        v = np.zeros(dim)
        # только если тип/сфера присутствуют в нашем idx
        if event.event_type in idx:
            v[idx[event.event_type]] = 1
        if event.event_sphere in idx:
            v[idx[event.event_sphere]] = 1
        return v

    # строим профиль пользователя
    profile = np.zeros(dim)
    cnt = 0
    for sub in user.subscriptions:
        if sub.status in ('visited', 'registered') and sub.event.date < now:
            profile += vec(sub.event)
            cnt += 1
    for fav in user.favorites:
        if fav.fav_type == 'type' and fav.fav_value in idx:
            profile[idx[fav.fav_value]] += 1
            cnt += 1
        if fav.fav_type == 'sphere' and fav.fav_value in idx:
            profile[idx[fav.fav_value]] += 1
            cnt += 1

    if cnt > 0:
        profile /= cnt
        # считаем косинусную похожесть
        for ev in upcoming:
            v = vec(ev)
            norm = np.linalg.norm(v) * np.linalg.norm(profile)
            sim = v.dot(profile) / norm if norm > 0 else 0
            if sim > 0.1:
                add_candidate(ev.id, 0.4 + sim * 0.6)

    # 2.6 Новые события ближайших 7 дней
    soon = now + timedelta(days=7)
    for ev in Event.query.filter(
            Event.date <= soon,
            Event.date > now,
            Event.is_approved
        ).all():
        add_candidate(ev.id, 0.7)

    # 3) Сортируем и берём топ-N
    ranked = sorted(candidates.items(), key=lambda x: -x[1])
    top_ids = [eid for eid, _ in ranked[:max_recs]]

    # 4) Сохраняем в таблицу UserRecommendation
    for eid in top_ids:
        db.session.add(UserRecommendation(user_id=user.id, event_id=eid))
    db.session.commit()
