"""Notification creation + recipient lookup helpers.

Pattern: every workflow event that's worth telling a user about goes
through `notify(...)` (single recipient) or `notify_users(...)` (a list,
typically resolved via the helpers below). Notifications are flushed in
the same DB session as the business change so a rollback on the action
also drops the notif — no orphan rows on failure.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Caterer, MembershipStatus, Notification, User, UserRole


def create_notification(
    session: Session,
    user_id,
    type,
    title,
    body,
    related_entity_type=None,
    related_entity_id=None,
):
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


# `notify` is the canonical short name used throughout the codebase for
# raising a notification at an event hook. It's a thin alias of
# `create_notification` — kept for callsite readability.
notify = create_notification


def notify_users(session: Session, user_ids, **kwargs):
    """Send the same notification to a list of users.

    `user_ids` may contain duplicates or None — both are filtered out so
    callers can pass the result of a recipient-resolver helper directly.
    Returns the list of created Notification rows.
    """
    seen = set()
    out = []
    for uid in user_ids:
        if not uid or uid in seen:
            continue
        seen.add(uid)
        out.append(create_notification(session, user_id=uid, **kwargs))
    return out


# ---------------------------------------------------------------------------
# Recipient resolvers — return user_ids to feed into notify_users().
# ---------------------------------------------------------------------------


def company_admin_user_ids(session: Session, company_id):
    """Active client_admin users of a given company. Used when an event
    targets « les administrateurs de la structure » (e.g. new pending
    member, invitation accepted)."""
    if company_id is None:
        return []
    return list(
        session.scalars(
            select(User.id).where(
                User.company_id == company_id,
                User.role == UserRole.client_admin,
                User.membership_status == MembershipStatus.active,
                User.is_active.is_(True),
            )
        )
    )


def caterer_user_ids(session: Session, caterer_id):
    """All users tied to a caterer (typically just one for now). Used
    when an event targets « le traiteur » (e.g. quote accepted, payment
    received)."""
    if caterer_id is None:
        return []
    return list(
        session.scalars(
            select(User.id).where(
                User.caterer_id == caterer_id,
                User.is_active.is_(True),
            )
        )
    )


def caterer_user_ids_for(session: Session, caterer):
    """Convenience overload when the caller already has the Caterer
    object in hand — saves a query."""
    if caterer is None:
        return []
    return caterer_user_ids(session, caterer.id)


def super_admin_user_ids(session: Session):
    """All super_admin users. Used to alert the qualification queue
    when a new demand arrives, a new caterer signs up, etc."""
    return list(
        session.scalars(
            select(User.id).where(
                User.role == UserRole.super_admin,
                User.is_active.is_(True),
            )
        )
    )


# `Caterer` is imported above only for the type-hinted helper signature
# above (`caterer_user_ids_for`) staying readable; reference it once so
# linters don't flag the import as unused.
_ = Caterer


def notification_target_url(note, role):
    """Resolve the in-app destination for a notification, or None if
    there's nothing to navigate to. The destination depends on both the
    related entity AND the user role (e.g. a `quote_request` notif
    points at /client/requests/<id> for a client_user but at
    /admin/qualification/<id> for a super_admin).

    Imports happen inside the function so this module stays usable
    from contexts without an active Flask app (CLI, tests).
    """
    from flask import url_for

    et = note.related_entity_type
    eid = note.related_entity_id
    if eid is None:
        return None

    if et == "quote_request":
        if role in ("client_admin", "client_user"):
            return url_for("client.request_detail", request_id=eid)
        if role == "caterer":
            return url_for("caterer.request_detail", qr_id=eid)
        if role == "super_admin":
            return url_for("admin.qualification_detail", request_id=eid)
        return None

    if et == "order":
        if role in ("client_admin", "client_user"):
            return url_for("client.order_detail", order_id=eid)
        if role == "caterer":
            return url_for("caterer.order_detail", order_id=eid)
        if role == "super_admin":
            return url_for("admin.order_detail", order_id=eid)
        return None

    if et == "quote":
        # Quote IDs aren't directly addressable client-side — bounce to
        # the parent request, which surfaces every quote in its sidebar.
        from database import get_db
        from models import Quote

        q = get_db().get(Quote, eid)
        if q is None:
            return None
        if role in ("client_admin", "client_user"):
            return url_for("client.request_detail", request_id=q.quote_request_id)
        if role == "caterer":
            return url_for("caterer.request_detail", qr_id=q.quote_request_id)
        return None

    if et == "user" and role == "client_admin":
        # Pending member to approve — the team page shows the queue.
        return url_for("client.team")

    if et == "caterer" and role == "super_admin":
        return url_for("admin.caterer_detail", caterer_id=eid)

    if et == "company" and role in ("client_admin", "client_user"):
        return url_for("client.dashboard")

    if et == "message":
        from database import get_db
        from models import Message

        msg = get_db().get(Message, eid)
        if msg is None:
            return None
        if role in ("client_admin", "client_user"):
            return url_for("client.message_thread", thread_id=msg.thread_id)
        if role == "caterer":
            return url_for("caterer.message_thread", thread_id=msg.thread_id)
        if role == "super_admin":
            # Admin messages page doesn't have a thread route yet — falls
            # back to the inbox.
            return url_for("admin.messages")

    return None


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
