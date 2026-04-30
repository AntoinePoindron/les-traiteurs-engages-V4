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
    ("casher", "Casher"),
    ("gluten_free", "Sans gluten"),
    ("lactose_free", "Sans lactose"),
]


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
