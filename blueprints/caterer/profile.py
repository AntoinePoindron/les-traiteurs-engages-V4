import json
import logging
from decimal import Decimal, InvalidOperation

from flask import flash, g, redirect, render_template, request, url_for
from pydantic import ValidationError

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.caterer import CatererProfileForm
from models import SERVICE_OFFERING_LABELS
from services.json_schemas import ServiceConfig
from services.uploads import save_upload

logger = logging.getLogger(__name__)


# Numeric fields stored per service offering. Keys map to input names like
# `spec[<slug>][capacity_min]` in the profile form.
_OFFERING_INT_FIELDS = ("capacity_min", "capacity_max", "min_advance_days")
_OFFERING_DECIMAL_FIELDS = ("price_per_person_min", "total_min")


def _parse_offering_specs(form) -> dict:
    """Read `spec[<slug>][<field>]` inputs into a clean dict.

    Unknown slugs are dropped, non-numeric values are silently coerced to
    None so a half-filled row doesn't crash the save. The returned shape
    is `{slug: {field: number_or_None}}` with empty rows omitted.
    """
    out: dict = {}
    for slug in SERVICE_OFFERING_LABELS:
        row: dict = {}
        for field in _OFFERING_INT_FIELDS:
            raw = form.get(f"spec[{slug}][{field}]") or ""
            raw = raw.strip()
            if not raw:
                continue
            try:
                row[field] = int(raw)
            except ValueError:
                continue
        for field in _OFFERING_DECIMAL_FIELDS:
            raw = form.get(f"spec[{slug}][{field}]") or ""
            raw = raw.strip().replace(",", ".")
            if not raw:
                continue
            try:
                row[field] = float(Decimal(raw))
            except (InvalidOperation, ValueError):
                continue
        if row:
            out[slug] = row
    return out


def _aggregate_legacy_fields(caterer, specs: dict) -> None:
    """Mirror per-offering specs onto the legacy global columns.

    Search/matching still reads caterer.capacity_min/max, price_per_person_min
    and min_advance_days, so we recompute them from the per-offering specs
    (min of mins, max of maxes) — keeping both surfaces consistent without a
    bigger refactor.
    """
    if not specs:
        return
    cap_mins = [s["capacity_min"] for s in specs.values() if s.get("capacity_min") is not None]
    cap_maxs = [s["capacity_max"] for s in specs.values() if s.get("capacity_max") is not None]
    price_mins = [s["price_per_person_min"] for s in specs.values() if s.get("price_per_person_min") is not None]
    advance = [s["min_advance_days"] for s in specs.values() if s.get("min_advance_days") is not None]
    if cap_mins:
        caterer.capacity_min = min(cap_mins)
    if cap_maxs:
        caterer.capacity_max = max(cap_maxs)
    if price_mins:
        caterer.price_per_person_min = Decimal(str(min(price_mins)))
    if advance:
        caterer.min_advance_days = min(advance)


def register(bp):
    @bp.route("/profile", methods=["GET"])
    @login_required
    @role_required("caterer")
    def profile():
        return render_template(
            "caterer/profile.html",
            user=g.current_user,
            caterer=g.current_user.caterer,
            service_offering_labels=SERVICE_OFFERING_LABELS,
        )

    @bp.route("/profile", methods=["POST"])
    @login_required
    @role_required("caterer")
    def profile_save():
        caterer = g.current_user.caterer
        form = CatererProfileForm()
        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            return render_template(
                "caterer/profile.html",
                user=g.current_user,
                caterer=caterer,
                service_offering_labels=SERVICE_OFFERING_LABELS,
            ), 400
        db = get_db()
        db.add(caterer)
        if form.name.data is not None:
            caterer.name = form.name.data or caterer.name
        if form.description.data is not None:
            caterer.description = form.description.data or caterer.description
        if form.address.data is not None:
            caterer.address = form.address.data or caterer.address
        if form.city.data is not None:
            caterer.city = form.city.data or caterer.city
        if form.zip_code.data is not None:
            caterer.zip_code = form.zip_code.data or caterer.zip_code
        if form.delivery_radius_km.data is not None:
            caterer.delivery_radius_km = form.delivery_radius_km.data
        caterer.dietary_vegetarian = form.dietary_vegetarian.data
        caterer.dietary_vegan = form.dietary_vegan.data
        caterer.dietary_halal = form.dietary_halal.data
        caterer.dietary_gluten_free = form.dietary_gluten_free.data
        caterer.dietary_lactose_free = form.dietary_lactose_free.data

        PHOTOS_MAX = 10
        existing_photos = set(caterer.photos or [])
        delete_urls = set(request.form.getlist("photo_delete"))
        requested_order = request.form.getlist("photos_order")
        new_files = [f for f in request.files.getlist("photos") if f and f.filename]
        new_iter = iter(new_files)

        final: list[str] = []
        for token in requested_order:
            if token == "__NEW__":
                file = next(new_iter, None)
                if file is None:
                    continue
                url = save_upload(file, subfolder="caterers")
                if url:
                    final.append(url)
            elif token in existing_photos and token not in delete_urls:
                final.append(token)

        for file in new_iter:
            url = save_upload(file, subfolder="caterers")
            if url:
                final.append(url)

        if not requested_order and not new_files:
            final = [u for u in (caterer.photos or []) if u not in delete_urls]

        caterer.photos = final[:PHOTOS_MAX]

        logo_file = request.files.get("logo")
        if logo_file and logo_file.filename:
            new_logo_url = save_upload(logo_file, subfolder="caterers/logos")
            if new_logo_url:
                caterer.logo_url = new_logo_url
            else:
                flash("Logo refuse : format ou taille invalide.", "error")
        elif request.form.get("logo_delete") == "1":
            caterer.logo_url = None

        # Catalog metadata. service_offerings comes through as a list of
        # checkbox values; validate against the canonical slug map so a
        # tampered request can't write an unknown slug to the JSON column.
        offered = [
            v for v in request.form.getlist("service_offerings")
            if v in SERVICE_OFFERING_LABELS
        ]
        caterer.service_offerings = offered or None

        # Per-offering specs replace the standalone capacity/price/délai
        # inputs. Only keep specs for offerings the caterer actually offers.
        all_specs = _parse_offering_specs(request.form)
        kept_specs = {slug: row for slug, row in all_specs.items() if slug in (offered or [])}
        caterer.service_offering_specs = kept_specs or None
        _aggregate_legacy_fields(caterer, kept_specs)

        service_config_raw = form.service_config.data or ""
        if service_config_raw:
            try:
                parsed = json.loads(service_config_raw)
                validated = ServiceConfig.model_validate(parsed)
                caterer.service_config = validated.model_dump()
            except json.JSONDecodeError:
                flash("Configuration JSON : syntaxe invalide.", "error")
                return redirect(url_for("caterer.profile"))
            except ValidationError as exc:
                first = exc.errors()[0]
                field = ".".join(str(p) for p in first["loc"]) or "(racine)"
                flash(f"Configuration JSON invalide en '{field}' : {first['msg']}.", "error")
                return redirect(url_for("caterer.profile"))
        db.commit()
        flash("Profil mis a jour.", "success")
        return redirect(url_for("caterer.profile"))
