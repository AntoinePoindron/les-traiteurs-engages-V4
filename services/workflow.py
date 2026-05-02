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
    Caterer,
    Order,
    OrderStatus,
    QRCStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
    User,
)
from services.matching import find_matching_caterers
from services.notifications import (
    caterer_user_ids,
    company_admin_user_ids,
    notify,
    notify_users,
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


class NoMatchingCaterers(WorkflowError):
    """Aucun traiteur compatible trouvé pour la demande (admin)."""


class OrderNotFound(WorkflowError):
    """La commande n'existe pas, n'appartient pas au caterer, ou n'est
    plus en statut `confirmed`."""


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

    # Notify the caterer that their quote was turned down. Reason (if
    # any) goes into the body so they can adjust their next proposal.
    body = "Votre devis a été refusé."
    if reason:
        body += f" Motif&nbsp;: {reason}"
    notify_users(
        db,
        caterer_user_ids(db, quote.caterer_id),
        type="quote_refused",
        title="Devis refusé",
        body=body,
        related_entity_type="quote_request",
        related_entity_id=request_id,
    )

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
    # VULN-41: SELECT FOR UPDATE on the request serializes concurrent
    # accept_quote calls so two clicks (or two tabs) cannot both create an
    # Order. Order.quote_id UNIQUE is a backstop, but locking earlier avoids
    # IntegrityError noise and double Stripe round-trips downstream.
    qr = db.execute(
        select(QuoteRequest)
        .where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if not qr:
        raise RequestNotFound

    # VULN-32: only requests that completed admin qualification can be acted on.
    # Skipping this check let a draft request whose quotes were somehow set to
    # `sent` slip through, bypassing approve_quote_request.
    if qr.status != QuoteRequestStatus.sent_to_caterers:
        raise QuoteNotAvailable

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

    others = (
        db.execute(
            select(Quote).where(
                Quote.quote_request_id == request_id,
                Quote.id != accepted.id,
                Quote.status == QuoteStatus.sent,
            )
        )
        .scalars()
        .all()
    )
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

    # Tell the winning caterer they got the deal. The losing caterers
    # already got their `status -> refused` flip silently — sending them
    # « un autre traiteur a été choisi » mails would be spammy and isn't
    # critical for V1.
    notify_users(
        db,
        caterer_user_ids(db, accepted.caterer_id),
        type="quote_accepted",
        title="Devis accepté !",
        body="Votre devis a été retenu. Une commande a été créée.",
        related_entity_type="order",
        related_entity_id=order.id,
    )
    return order


def approve_quote_request(
    db,
    *,
    request_id: uuid.UUID,
) -> list[QuoteRequestCaterer]:
    """Qualification admin : matche les traiteurs compatibles, crée les QRC
    en `selected`, passe la demande en `sent_to_caterers`.

    Le contrôle d'autorisation reste côté handler (`@role_required("super_admin")`).

    Lève RequestNotFound, NoMatchingCaterers.
    """
    qr = db.get(QuoteRequest, request_id)
    if not qr:
        raise RequestNotFound

    matches = find_matching_caterers(db, qr)
    if not matches:
        raise NoMatchingCaterers

    qrcs: list[QuoteRequestCaterer] = []
    for caterer, _distance in matches:
        qrc = QuoteRequestCaterer(
            quote_request_id=qr.id,
            caterer_id=caterer.id,
            status=QRCStatus.selected,
        )
        db.add(qrc)
        qrcs.append(qrc)

    qr.status = QuoteRequestStatus.sent_to_caterers

    # Tell each matched caterer they have a new demand to consider, and
    # tell the original requester that their demand has been validated
    # and forwarded.
    for caterer, _distance in matches:
        notify_users(
            db,
            caterer_user_ids(db, caterer.id),
            type="quote_request_received",
            title="Nouvelle demande de devis",
            body=f"Une demande pour {qr.guest_count or '?'} convives "
            f"({qr.event_city or 'lieu non renseigné'}) vous a été transmise.",
            related_entity_type="quote_request",
            related_entity_id=qr.id,
        )
    if qr.user_id is not None:
        notify(
            db,
            user_id=qr.user_id,
            type="quote_request_approved",
            title="Votre demande a été transmise",
            body=f"Votre demande a été envoyée à {len(matches)} traiteur(s) compatibles.",
            related_entity_type="quote_request",
            related_entity_id=qr.id,
        )
    db.flush()
    return qrcs


def reject_quote_request(
    db,
    *,
    request_id: uuid.UUID,
    reason: str | None,
) -> None:
    """Rejet admin d'une demande de devis. Stocke la raison sur la demande.

    Lève RequestNotFound.
    """
    qr = db.get(QuoteRequest, request_id)
    if not qr:
        raise RequestNotFound
    qr.status = QuoteRequestStatus.cancelled
    qr.message_to_caterer = reason or ""

    # Let the requester know their demand was rejected by the platform
    # admin (with the reason if they provided one).
    if qr.user_id is not None:
        body = "Votre demande de devis a été refusée par notre équipe."
        if reason:
            body += f" Motif&nbsp;: {reason}"
        notify(
            db,
            user_id=qr.user_id,
            type="quote_request_rejected",
            title="Demande refusée",
            body=body,
            related_entity_type="quote_request",
            related_entity_id=qr.id,
        )


def submit_quote(
    db,
    *,
    request_id: uuid.UUID,
    quote_id: uuid.UUID,
    caterer: Caterer,
) -> Quote:
    """Le traiteur soumet un devis : flip Quote→sent, QRC→responded.

    Règle des 3 premiers répondants :
    - tant que <3 QRC sont en `transmitted_to_client`, le devis est transmis
      au client et `response_rank` enregistré (1, 2 ou 3) ;
    - le 3e répondant déclenche la fermeture des QRC `selected` restants.
    Au-delà : le QRC reste en `responded` mais n'est pas transmis.

    Sérialisation : `SELECT ... FOR UPDATE` sur la QR pose un verrou
    exclusif jusqu'au commit, ce qui empêche deux répondants simultanés
    d'atteindre tous les deux le rang 3.

    Lève QuoteNotFound (devis introuvable, mauvais caterer, ou pas en `draft`).
    """
    # Verrou exclusif pour sérialiser les répondants concurrents.
    db.execute(
        select(QuoteRequest.id).where(QuoteRequest.id == request_id).with_for_update()
    )

    quote = db.scalar(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.caterer_id == caterer.id,
            Quote.quote_request_id == request_id,
            Quote.status == QuoteStatus.draft,
        )
    )
    if not quote:
        raise QuoteNotFound

    qrc = db.scalar(
        select(QuoteRequestCaterer).where(
            QuoteRequestCaterer.quote_request_id == request_id,
            QuoteRequestCaterer.caterer_id == caterer.id,
        )
    )
    if not qrc:
        raise QuoteNotFound

    quote.status = QuoteStatus.sent
    qrc.status = QRCStatus.responded
    qrc.responded_at = datetime.datetime.utcnow()

    transmitted = db.scalar(
        select(func.count(QuoteRequestCaterer.id))
        .where(QuoteRequestCaterer.quote_request_id == request_id)
        .where(QuoteRequestCaterer.status == QRCStatus.transmitted_to_client)
    )

    if transmitted < 3:
        qrc.status = QRCStatus.transmitted_to_client
        qrc.response_rank = transmitted + 1
        if transmitted + 1 == 3:
            remaining = db.scalars(
                select(QuoteRequestCaterer)
                .where(QuoteRequestCaterer.quote_request_id == request_id)
                .where(QuoteRequestCaterer.status == QRCStatus.selected)
                .where(QuoteRequestCaterer.caterer_id != caterer.id)
            ).all()
            for r in remaining:
                r.status = QRCStatus.closed

        # The quote actually reaches the client only when the QRC flips
        # to `transmitted_to_client` (rank ≤ 3). Notify the requester
        # so they come check it out.
        qr_obj = db.get(QuoteRequest, request_id)
        if qr_obj is not None and qr_obj.user_id is not None:
            notify(
                db,
                user_id=qr_obj.user_id,
                type="quote_received",
                title="Nouveau devis reçu",
                body=f"{caterer.name} vient de vous envoyer un devis.",
                related_entity_type="quote",
                related_entity_id=quote.id,
            )

    db.flush()
    return quote


def mark_delivered(
    db,
    *,
    order_id: uuid.UUID,
    caterer: Caterer,
) -> Order:
    """Le traiteur passe la commande de `confirmed` à `delivered`.

    Préserve à l'identique la surface du handler `caterer.order_deliver` :
    seules les commandes en `confirmed` du caterer authentifié transitionnent.
    Le déclenchement de la facturation Stripe reste côté handler pour
    cette PR ; il sera découplé en deux phases dans la PR B.

    Lève OrderNotFound.
    """
    order = db.scalar(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .where(Order.id == order_id)
        .where(Quote.caterer_id == caterer.id)
        .where(Order.status == OrderStatus.confirmed)
        .with_for_update()
    )
    if not order:
        raise OrderNotFound
    order.status = OrderStatus.delivered

    # Tell the company admins their commande just got marked delivered
    # by the caterer. They'll typically expect an invoice next.
    qr = order.quote.quote_request
    notify_users(
        db,
        company_admin_user_ids(db, qr.company_id),
        type="order_delivered",
        title="Commande marquée comme livrée",
        body=f"{caterer.name} a marqué la commande comme livrée.",
        related_entity_type="order",
        related_entity_id=order.id,
    )
    return order
