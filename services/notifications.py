from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Notification


def create_notification(session: Session, user_id, type, title, body, related_entity_type=None, related_entity_id=None):
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
    )
    session.add(notification)
    return notification


def get_unread_count(session: Session, user_id):
    return session.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.is_read.is_(False),
        )
    )


def mark_as_read(session: Session, notification_id):
    notification = session.get(Notification, notification_id)
    if notification:
        notification.is_read = True
    return notification
