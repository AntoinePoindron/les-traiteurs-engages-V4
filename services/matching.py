import math

from sqlalchemy import select

from models import Caterer


def haversine_km(lat1, lng1, lat2, lng2):
    """Distance in km between two GPS points."""
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


DIETARY_FIELDS = [
    "dietary_vegetarian",
    "dietary_vegan",
    "dietary_halal",
    "dietary_gluten_free",
    "dietary_lactose_free",
]


def find_matching_caterers(session, quote_request):
    """Return list of (Caterer, distance_km) sorted by distance then name."""
    if quote_request.event_latitude is None or quote_request.event_longitude is None:
        return []

    caterers = session.scalars(
        select(Caterer).where(Caterer.is_validated.is_(True))
    ).all()
    results = []

    for caterer in caterers:
        if caterer.latitude is None or caterer.longitude is None:
            continue

        distance = haversine_km(
            quote_request.event_latitude,
            quote_request.event_longitude,
            caterer.latitude,
            caterer.longitude,
        )

        if caterer.delivery_radius_km and distance > caterer.delivery_radius_km:
            continue

        if quote_request.guest_count is not None:
            if (
                caterer.capacity_min
                and quote_request.guest_count < caterer.capacity_min
            ):
                continue
            if (
                caterer.capacity_max
                and quote_request.guest_count > caterer.capacity_max
            ):
                continue

        if not _dietary_compatible(quote_request, caterer):
            continue

        if not _service_compatible(quote_request, caterer):
            continue

        results.append((caterer, round(distance, 1)))

    results.sort(key=lambda pair: (pair[1], pair[0].name))
    return results


def _dietary_compatible(request, caterer):
    for field in DIETARY_FIELDS:
        if getattr(request, field) and not getattr(caterer, field):
            return False
    return True


def _service_compatible(request, caterer):
    # No declared offerings → don't penalise the caterer (legacy fiches
    # may not have filled their catalog yet); same with a request that
    # doesn't pin a meal_type. Otherwise the caterer matches iff the
    # request's meal_type slug appears in their published offerings.
    if not request.meal_type or not caterer.service_offerings:
        return True
    meal = (
        request.meal_type.value
        if hasattr(request.meal_type, "value")
        else request.meal_type
    )
    return meal in caterer.service_offerings
