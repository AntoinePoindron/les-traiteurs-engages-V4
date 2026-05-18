import uuid

from sqlalchemy import select

from models import ALCOHOLIC_DRINKS, CompanyService, DRINK_LABELS


ITEMS_PER_PAGE = 12

STATUS_TABS = {
    "all": "Toutes",
    "draft": "Brouillons",
    "pending_review": "En attente",
    "sent_to_caterers": "Envoyees",
    "completed": "Terminees",
}

ORDER_STATUS_LABELS = {
    "confirmed": "Confirmee",
    "delivered": "Livree",
    "invoiced": "Facturee",
    "paid": "Payee",
    "disputed": "Contestee",
}

STRUCTURE_GROUPS = {
    "STPA": ["ESAT", "EA"],
    "SIAE": ["EI", "ACI"],
}

DIETARY_FLAGS = [
    ("vegetarian", "Vegetarien"),
    ("vegan", "Vegan"),
    ("halal", "Halal"),
    ("gluten_free", "Sans gluten"),
    ("lactose_free", "Sans lactose"),
]


# Fields copied verbatim from QuoteRequestForm to QuoteRequest.
_QR_DIRECT_FIELDS = (
    "event_date",
    "event_start_time",
    "event_end_time",
    "guest_count",
    "event_latitude",
    "event_longitude",
    "budget_global",
    "budget_per_person",
    "dietary_vegetarian",
    "dietary_vegan",
    "dietary_halal",
    "dietary_gluten_free",
    "dietary_lactose_free",
    "vegetarian_count",
    "vegan_count",
    "halal_count",
    "gluten_free_count",
    "lactose_free_count",
    # `drinks_alcohol` is derived from the `drinks` list in
    # `apply_drinks` — keep it out of the verbatim-copy list so a
    # tampered POST can't lie about alcohol without ticking the
    # actual drink.
    "wants_waitstaff",
    "wants_equipment",
    "wants_decoration",
    "wants_nappes",
    "wants_livraison",
    "wants_setup",
    "service_setup_time",
    "wants_cleanup",
    "is_compare_mode",
)

# Fields where empty strings should become None.
_QR_OPTIONAL_FIELDS = (
    "service_type",
    "meal_type",
    "event_address",
    "event_city",
    "event_zip_code",
    "drinks_details",
    "service_waitstaff_details",
    "service_setup_details",
    "message_to_caterer",
)


def apply_quote_request_form(qr, form):
    """Copy validated form fields onto a QuoteRequest instance.

    Does NOT cover the wizard step-5 drink checkboxes — those live
    outside WTForms (no FieldList for dynamic checkbox groups) and are
    persisted by `apply_drinks(qr, request.form)`. Every handler that
    creates or edits a QuoteRequest must call both.
    """
    for field in _QR_DIRECT_FIELDS:
        setattr(qr, field, getattr(form, field).data)
    for field in _QR_OPTIONAL_FIELDS:
        setattr(qr, field, getattr(form, field).data or None)


def apply_drinks(qr, request_form):
    """Persist the wizard step-5 drink selection onto `qr`.

    `request_form` is `flask.request.form`. The wizard exposes one
    checkbox per slug in `DRINK_LABELS`; checkboxes WTForms doesn't see
    (no FieldList for dynamic checkbox groups), so we read them off the
    raw form. Unknown keys are ignored — a tampered POST that smuggles
    `drinks_unicorn=1` simply doesn't land in the list.

    Must be called next to `apply_quote_request_form` from every
    handler that creates or edits a QuoteRequest, since it operates on
    the raw `request.form` (not the WTForms instance) and so the
    standard applier can't pick it up.

    `drinks_alcohol` is recomputed from the selection so the legacy
    boolean stays trustworthy without trusting the client to set it.
    """
    # An unticked checkbox emits no key, so a present key normally
    # means "ticked". Accept only the truthy values the browser would
    # actually send so a forged POST with `drinks_eau_plate=0` doesn't
    # smuggle a checkbox in.
    selected = [
        slug
        for slug in DRINK_LABELS
        if request_form.get(slug, "").strip().lower() in ("1", "true", "on", "yes")
    ]
    qr.drinks = selected or None
    qr.drinks_alcohol = any(slug in ALCOHOLIC_DRINKS for slug in selected)


def own_service_id(db, user, raw):
    """Return the parsed UUID iff it names a CompanyService owned by `user`."""
    if not raw:
        return None
    try:
        candidate = uuid.UUID(raw)
    except (ValueError, TypeError):
        return None
    return db.scalar(
        select(CompanyService.id).where(
            CompanyService.id == candidate,
            CompanyService.company_id == user.company_id,
        )
    )
