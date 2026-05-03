import uuid

from sqlalchemy import select

from models import CompanyService


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
    "drinks_alcohol",
    "wants_waitstaff",
    "wants_equipment",
    "wants_decoration",
    "wants_setup",
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
    "message_to_caterer",
)


def apply_quote_request_form(qr, form):
    """Copy validated form fields onto a QuoteRequest instance."""
    for field in _QR_DIRECT_FIELDS:
        setattr(qr, field, getattr(form, field).data)
    for field in _QR_OPTIONAL_FIELDS:
        setattr(qr, field, getattr(form, field).data or None)


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
