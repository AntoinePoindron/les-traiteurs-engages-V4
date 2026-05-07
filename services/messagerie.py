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


def threads_for_admin(db: Session, *, page: int, page_size: int):
    """Paginated thread list for the super_admin observer view.

    Each thread is summarised from the perspective of "the participant
    that isn't the platform" — picks the caterer-side participant when
    one exists (so the admin sees a caterer-keyed row), otherwise the
    sender. Returns (rows, total).
    """
    total = db.scalar(select(func.count(func.distinct(Message.thread_id)))) or 0

    summaries = db.execute(
        select(
            Message.thread_id.label("thread_id"),
            func.max(Message.created_at).label("last_at"),
        )
        .group_by(Message.thread_id)
        .order_by(func.max(Message.created_at).desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    if not summaries:
        return [], total

    thread_ids = [s.thread_id for s in summaries]

    last_messages = (
        db.execute(
            select(Message)
            .where(Message.thread_id.in_(thread_ids))
            .order_by(Message.thread_id, Message.created_at.desc())
            .distinct(Message.thread_id)
        )
        .scalars()
        .all()
    )
    last_by_thread = {m.thread_id: m for m in last_messages}

    user_ids = set()
    for m in last_messages:
        user_ids.add(m.sender_id)
        user_ids.add(m.recipient_id)
    users = (
        {
            u.id: u
            for u in db.execute(select(User).where(User.id.in_(user_ids)))
            .scalars()
            .all()
        }
        if user_ids
        else {}
    )

    rows: list[dict] = []
    for tid in thread_ids:
        msg = last_by_thread.get(tid)
        if not msg:
            continue
        sender = users.get(msg.sender_id)
        recipient = users.get(msg.recipient_id)
        # Pick the caterer-side participant as the "subject" of the row
        # when one exists; otherwise default to the sender.
        if sender and sender.role == UserRole.caterer:
            other_user = sender
        elif recipient and recipient.role == UserRole.caterer:
            other_user = recipient
        else:
            other_user = sender or recipient
        rows.append(
            _summarise_thread(
                viewer_id=None,
                other_user=other_user,
                last_message=msg,
                unread=0,  # admin view doesn't track per-admin unread
            )
        )
    return rows, total


def find_thread_with(db: Session, *, viewer, other_user_id):
    """Return the thread_id of the (viewer, other_user) pair, or None
    if they've never exchanged a message yet.

    Used by the "go to conversation with X" entry points so the same
    button reuses an existing thread or falls through to compose-new.
    """
    if not other_user_id:
        return None
    return db.scalar(
        select(Message.thread_id)
        .where(
            or_(
                (Message.sender_id == viewer.id)
                & (Message.recipient_id == other_user_id),
                (Message.sender_id == other_user_id)
                & (Message.recipient_id == viewer.id),
            )
        )
        .limit(1)
    )


def compose_thread_context(
    db: Session,
    *,
    viewer,
    other_user_id,
    order_id=None,
    quote_request_id=None,
) -> dict | None:
    """Build a right-pane "compose new conversation" context — same
    shape as `active_thread_context` but with no `thread_id` yet.

    The template renders the empty conversation pane + the message
    form pre-filled with `other_user_id`; messages.js skips the
    initial load (no thread to fetch) and adopts the thread_id
    returned by the API after the first send.

    `order_id` / `quote_request_id` flow through to hidden inputs in
    the form so the first POST satisfies the VULN-04 business-relation
    gate in /api/messages — without an explicit context, the API
    rejects messages that have no inheritable thread history.

    Returns None if the target user doesn't exist or is the viewer
    themselves (which the UI shouldn't allow but we guard anyway).
    """
    if not other_user_id or str(other_user_id) == str(viewer.id):
        return None
    other_user = db.get(User, other_user_id)
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
        "compose_order_id": str(order_id) if order_id else None,
        "compose_quote_request_id": (
            str(quote_request_id) if quote_request_id else None
        ),
    }


def active_thread_context(db: Session, *, thread_id, viewer) -> dict | None:
    """Build the "active" pane dict (right side) for a given thread.

    Returns None if the viewer has no access (no message in the thread
    that they sent or received) — caller maps to abort(404).
    Super_admin sees every thread regardless of participation.
    """
    base_q = select(Message).where(Message.thread_id == thread_id)
    if viewer.role != UserRole.super_admin:
        base_q = base_q.where(
            or_(Message.sender_id == viewer.id, Message.recipient_id == viewer.id)
        )
    first_msg = db.scalar(base_q)
    if not first_msg:
        return None

    if viewer.role == UserRole.super_admin:
        # Mirror the row-pick rule: caterer side wins when possible.
        sender = db.get(User, first_msg.sender_id)
        recipient = db.get(User, first_msg.recipient_id)
        if sender and sender.role == UserRole.caterer:
            other_user = sender
        elif recipient and recipient.role == UserRole.caterer:
            other_user = recipient
        else:
            other_user = sender or recipient
    else:
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
