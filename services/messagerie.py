"""Builders for the unified Messagerie context dict.

Centralises the role/avatar derivation logic so the three blueprints
(client, caterer, super_admin) don't drift on the visual contract that
`templates/messagerie/_panes.html` relies on.

Design notes :
  * `_other_user_view` is a small dict (not a User instance) so the
    template stays Python-free and we don't accidentally pull in the
    SQLAlchemy session inside Jinja.
  * `detail_url_for` is intentionally narrow — it covers the
    "Voir le détail" CTA in the right-pane header. When there's no
    sensible target for the current viewer ↔ other_user pair (e.g. a
    caterer messaging a client, since clients have no public profile),
    it returns None and the template hides the button.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from flask import url_for

from models import Message, User, UserRole


def _avatar_for_user(other_user) -> tuple[str | None, str]:
    """Return (avatar_url, avatar_kind) for the messagerie row/header.

    `kind` drives the fallback icon when no logo is available
    ('caterer' → store icon, otherwise → building icon).
    """
    if other_user is None:
        return None, "unknown"
    if other_user.role == UserRole.caterer and other_user.caterer:
        return other_user.caterer.logo_url, "caterer"
    if other_user.company:
        return other_user.company.logo_url, "client"
    return None, "unknown"


def _entity_name(other_user) -> str:
    """Display name = company / caterer name (matches the mockup),
    falling back to "FirstName LastName" when neither is set."""
    if other_user is None:
        return "Inconnu"
    if other_user.role == UserRole.caterer and other_user.caterer:
        return other_user.caterer.name
    if other_user.company:
        return other_user.company.name
    return f"{other_user.first_name} {other_user.last_name}"


def detail_url_for(viewer, other_user) -> str | None:
    """Resolve the "Voir le détail" target URL for a (viewer, other) pair.

    Returns None when no clean target exists (e.g. caterer messaging a
    client — clients don't have a public profile in V1).
    """
    if other_user is None:
        return None
    if viewer.role == UserRole.super_admin:
        if other_user.role == UserRole.caterer and other_user.caterer:
            return url_for("admin.caterer_detail", caterer_id=other_user.caterer.id)
        if other_user.company:
            return url_for("admin.company_detail", company_id=other_user.company.id)
        return None
    if viewer.role in (UserRole.client_admin, UserRole.client_user):
        if other_user.role == UserRole.caterer and other_user.caterer:
            return url_for("client.caterer_detail", caterer_id=other_user.caterer.id)
        return None
    # Caterer messaging a client: no public profile to link to.
    return None


def _summarise_thread(
    *,
    viewer_id,
    other_user,
    last_message: Message,
    unread: int,
) -> dict:
    avatar_url, avatar_kind = _avatar_for_user(other_user)
    return {
        "thread_id": str(last_message.thread_id),
        "other_user_id": str(other_user.id) if other_user else None,
        "other_name": _entity_name(other_user),
        # `User.role` is stored as a plain String column — comparing to a
        # UserRole enum works because UserRole subclasses str, but `.value`
        # would only exist on a real enum instance. Pass through as-is.
        "other_role": str(other_user.role) if other_user else "unknown",
        "other_avatar_url": avatar_url,
        "other_avatar_kind": avatar_kind,
        "last_message": (last_message.body or "")[:80],
        "last_at": last_message.created_at,
        "unread": unread,
    }


def threads_for_viewer(db: Session, viewer) -> list[dict]:
    """Return thread summaries for a regular participant (client or caterer).

    One row per thread, ordered by most recent message first. Designed
    for the left pane of the messagerie.

    Three queries total regardless of how many messages the viewer has:
      1. Latest message per thread via PostgreSQL DISTINCT ON.
      2. Unread counts per thread via a single GROUP BY.
      3. Bulk-fetch the involved users.
    """
    last_messages = db.scalars(
        select(Message)
        .where(or_(Message.sender_id == viewer.id, Message.recipient_id == viewer.id))
        .order_by(Message.thread_id, Message.created_at.desc())
        .distinct(Message.thread_id)
    ).all()
    if not last_messages:
        return []

    # Final ordering: most recent activity first. DISTINCT ON's required
    # ordering above is by thread_id; we re-sort here for the UI.
    last_messages.sort(key=lambda m: m.created_at, reverse=True)

    unread_by_thread = dict(
        db.execute(
            select(Message.thread_id, func.count(Message.id))
            .where(
                Message.recipient_id == viewer.id,
                Message.is_read.is_(False),
            )
            .group_by(Message.thread_id)
        ).all()
    )

    other_ids = {
        msg.recipient_id if msg.sender_id == viewer.id else msg.sender_id
        for msg in last_messages
    }
    other_ids.discard(None)
    users_by_id = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(other_ids))).all()}
        if other_ids
        else {}
    )

    return [
        _summarise_thread(
            viewer_id=viewer.id,
            other_user=users_by_id.get(
                msg.recipient_id if msg.sender_id == viewer.id else msg.sender_id
            ),
            last_message=msg,
            unread=unread_by_thread.get(msg.thread_id, 0),
        )
        for msg in last_messages
    ]


def active_thread_context(db: Session, *, thread_id, viewer) -> dict | None:
    """Build the "active" pane dict (right side) for a given thread.

    Returns None if the viewer has no access (no message in the thread
    that they sent or received) — caller maps to abort(404). Every role,
    super_admin included, is gated on participation: the admin reads and
    replies to its own conversations, not the whole platform's.
    """
    first_msg = db.scalar(
        select(Message)
        .where(Message.thread_id == thread_id)
        .where(or_(Message.sender_id == viewer.id, Message.recipient_id == viewer.id))
    )
    if not first_msg:
        return None

    other_id = (
        first_msg.recipient_id
        if first_msg.sender_id == viewer.id
        else first_msg.sender_id
    )
    other_user = db.get(User, other_id) if other_id else None
    if other_user is None:
        return None

    avatar_url, avatar_kind = _avatar_for_user(other_user)
    contact_full_name = (
        f"{other_user.first_name} {other_user.last_name}".strip()
        if other_user.first_name or other_user.last_name
        else ""
    )
    return {
        "other_user_id": str(other_user.id),
        "other_name": _entity_name(other_user),
        "other_role": str(other_user.role),
        "other_avatar_url": avatar_url,
        "other_avatar_kind": avatar_kind,
        "contact_full_name": contact_full_name,
        "detail_url": detail_url_for(viewer, other_user),
    }
