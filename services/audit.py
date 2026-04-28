"""Append-only admin audit logging.

Call `log_admin_action()` from the handler that performs a sensitive action,
right before `db.commit()`. The entry will be flushed atomically with the
business change — either both happen, or neither does (no orphan logs, no
silent actions).

Never delete rows from `audit_logs` from application code.
"""
from __future__ import annotations

import uuid
from typing import Any

from flask import has_request_context, request

from models import AuditLog, User


def log_admin_action(
    db,
    actor: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append one row to audit_logs.

    Args:
        db: SQLAlchemy session.
        actor: the User performing the action (typically `g.current_user`).
            None is accepted for system-driven actions.
        action: short identifier in `domain.verb` format, e.g.
            `caterer.validate`, `quote_request.reject`. Indexed.
        target_type: the kind of entity acted on (`caterer`, `quote_request`,
            `order`, etc.). Optional but strongly encouraged.
        target_id: UUID of the entity. Indexed.
        extra: free-form JSON-serialisable dict for context (rejection
            reason, before/after snapshot, etc.). Keep small (<2 KB).
    """
    ip = None
    ua = None
    if has_request_context():
        ip = request.remote_addr
        ua = (request.user_agent.string or "")[:500] or None

    db.add(AuditLog(
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        extra=extra,
        ip_address=ip,
        user_agent=ua,
    ))
