"""Domain transitions de statut métier.

Conventions :
- 1er argument = `db` (session SQLAlchemy). Tout le reste en kwargs.
- Aucune fonction ne commit : le caller (handler HTTP, CLI) commit.
- Rejet métier = exception typée (sous-classe de `WorkflowError`).
- Pas d'import Flask : pas de `g`, pas de `request`, pas de `flash`.

But : transitions testables sans contexte HTTP, point d'entrée unique
par règle métier, démarcation transactionnelle visible côté caller.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from models import (
    Quote,
    QuoteRequest,
    QuoteRequestStatus,
    QuoteStatus,
    User,
)


class WorkflowError(Exception):
    """Rejet métier : le caller mappe sur flash + redirect."""


class RequestNotFound(WorkflowError):
    """La demande de devis n'existe pas dans le scope de l'appelant."""


class QuoteNotFound(WorkflowError):
    """Le devis n'existe pas, ou n'appartient pas à la demande."""


def refuse_quote(
    db,
    *,
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    user: User,
    reason: str | None,
) -> None:
    """Refuse un devis. Si plus aucun devis n'est en `sent`, passe la
    demande en `quotes_refused`.

    Reproduit à l'identique le comportement de `blueprints/client.py:refuse_quote`
    pour que cette extraction soit visiblement no-op. Les durcissements
    éventuels (filtrer `quote.status == sent`, par exemple) sont des
    commits séparés.
    """
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        raise RequestNotFound

    quote = db.execute(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.quote_request_id == request_id,
        )
    ).scalar_one_or_none()
    if not quote:
        raise QuoteNotFound

    quote.status = QuoteStatus.refused
    quote.refusal_reason = reason or None

    remaining = db.execute(
        select(func.count(Quote.id)).where(
            Quote.quote_request_id == request_id,
            Quote.status == QuoteStatus.sent,
        )
    ).scalar_one()

    if remaining == 0:
        qr.status = QuoteRequestStatus.quotes_refused
