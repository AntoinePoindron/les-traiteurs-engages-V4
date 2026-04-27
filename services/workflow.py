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

import datetime
import uuid

from sqlalchemy import func, select

from models import (
    Order,
    OrderStatus,
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


class QuoteNotAvailable(WorkflowError):
    """Le devis n'est pas en statut `sent` (déjà accepté, refusé, draft)."""


class QuoteExpired(WorkflowError):
    """La date de validité du devis est dépassée."""


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


def accept_quote(
    db,
    *,
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    user: User,
) -> Order:
    """Accepte un devis, refuse les autres, crée la commande, clôt la demande.

    Garde-fous (audit #5) : seul un quote en statut `sent` et non expiré peut
    être accepté. Les pairs en `sent` sont passés en `refused`. La demande
    passe en `completed`.

    Lève RequestNotFound (404), QuoteNotAvailable / QuoteExpired (flash).
    """
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        raise RequestNotFound

    accepted = db.execute(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.quote_request_id == request_id,
            Quote.status == QuoteStatus.sent,
        )
    ).scalar_one_or_none()
    if not accepted:
        raise QuoteNotAvailable

    if accepted.valid_until and accepted.valid_until < datetime.date.today():
        raise QuoteExpired

    accepted.status = QuoteStatus.accepted

    others = db.execute(
        select(Quote).where(
            Quote.quote_request_id == request_id,
            Quote.id != accepted.id,
            Quote.status == QuoteStatus.sent,
        )
    ).scalars().all()
    for q in others:
        q.status = QuoteStatus.refused
        q.refusal_reason = "Un autre devis a ete accepte."

    order = Order(
        quote_id=accepted.id,
        client_admin_id=user.id,
        status=OrderStatus.confirmed,
        delivery_date=qr.event_date,
        delivery_address=f"{qr.event_address}, {qr.event_zip_code} {qr.event_city}",
    )
    db.add(order)
    db.flush()

    qr.status = QuoteRequestStatus.completed
    return order
