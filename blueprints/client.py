import datetime
import math
import uuid

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from blueprints.middleware import login_required, role_required
from database import get_db
from services.uploads import save_upload
from models import (
    Caterer,
    CatererStructureType,
    Company,
    CompanyEmployee,
    CompanyService,
    MembershipStatus,
    Message,
    Order,
    OrderStatus,
    Quote,
    QuoteRequest,
    QuoteRequestCaterer,
    QuoteRequestStatus,
    QuoteStatus,
    User,
)

ITEMS_PER_PAGE = 12

STRUCTURE_GROUPS = {
    "STPA": [CatererStructureType.ESAT, CatererStructureType.EA],
    "SIAE": [CatererStructureType.EI, CatererStructureType.ACI],
}

DIETARY_FLAGS = [
    ("vegetarian", "Vegetarien"),
    ("vegan", "Vegan"),
    ("halal", "Halal"),
    ("casher", "Casher"),
    ("gluten_free", "Sans gluten"),
    ("lactose_free", "Sans lactose"),
]

client_bp = Blueprint("client", __name__, url_prefix="/client")

MEAL_TYPE_LABELS = {
    "petit_dejeuner": "Petit-dejeuner",
    "dejeuner": "Dejeuner",
    "diner": "Diner",
    "cocktail": "Cocktail",
    "autre": "Autre",
}

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


@client_bp.route("/dashboard")
@login_required
@role_required("client_admin", "client_user")
def dashboard():
    user = g.current_user
    db = get_db()
    active_requests_count = db.execute(
        select(func.count(QuoteRequest.id)).where(
            QuoteRequest.company_id == user.company_id,
            QuoteRequest.status.in_([
                QuoteRequestStatus.draft,
                QuoteRequestStatus.pending_review,
                QuoteRequestStatus.sent_to_caterers,
            ]),
        )
    ).scalar_one()

    recent_orders = db.execute(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
        .where(QuoteRequest.company_id == user.company_id)
        .order_by(Order.created_at.desc())
        .limit(5)
    ).scalars().all()

    services = db.execute(
        select(CompanyService).where(CompanyService.company_id == user.company_id)
    ).scalars().all()

    budget_data = []
    for service in services:
        spent = db.execute(
            select(func.coalesce(func.sum(Quote.total_amount_ht), 0)).where(
                Quote.quote_request_id.in_(
                    select(QuoteRequest.id).where(
                        QuoteRequest.company_service_id == service.id,
                    )
                ),
                Quote.status == QuoteStatus.accepted,
            )
        ).scalar_one()
        budget_data.append({
            "name": service.name,
            "budget": float(service.annual_budget or 0),
            "spent": float(spent),
        })

    return render_template(
        "client/dashboard.html",
        user=user,
        active_requests_count=active_requests_count,
        recent_orders=recent_orders,
        budget_data=budget_data,
        order_status_labels=ORDER_STATUS_LABELS,
    )


@client_bp.route("/requests")
@login_required
@role_required("client_admin", "client_user")
def requests_list():
    user = g.current_user
    status_filter = request.args.get("status", "all")
    db = get_db()
    stmt = select(QuoteRequest).where(
        QuoteRequest.company_id == user.company_id
    ).order_by(QuoteRequest.created_at.desc())

    if status_filter == "draft":
        stmt = stmt.where(QuoteRequest.status == QuoteRequestStatus.draft)
    elif status_filter == "pending_review":
        stmt = stmt.where(QuoteRequest.status == QuoteRequestStatus.pending_review)
    elif status_filter == "sent_to_caterers":
        stmt = stmt.where(QuoteRequest.status == QuoteRequestStatus.sent_to_caterers)
    elif status_filter == "completed":
        stmt = stmt.where(QuoteRequest.status.in_([
            QuoteRequestStatus.completed,
            QuoteRequestStatus.cancelled,
            QuoteRequestStatus.quotes_refused,
        ]))

    requests = db.execute(stmt).scalars().all()

    return render_template(
        "client/requests/list.html",
        user=user,
        requests=requests,
        current_tab=status_filter,
        tabs=STATUS_TABS,
        meal_type_labels=MEAL_TYPE_LABELS,
    )


@client_bp.route("/requests/new", methods=["GET"])
@login_required
@role_required("client_admin", "client_user")
def requests_new():
    user = g.current_user
    db = get_db()
    services = db.execute(
        select(CompanyService).where(CompanyService.company_id == user.company_id)
    ).scalars().all()
    return render_template("client/requests/new.html", user=user, services=services)


@client_bp.route("/requests/new", methods=["POST"])
@login_required
@role_required("client_admin", "client_user")
def requests_new_post():
    user = g.current_user
    form = request.form

    is_compare = form.get("is_compare_mode") == "1"
    status = QuoteRequestStatus.pending_review if is_compare else QuoteRequestStatus.sent_to_caterers

    service_id = form.get("company_service_id") or None
    if service_id:
        service_id = uuid.UUID(service_id)

    budget_global = float(form["budget_global"]) if form.get("budget_global") else None
    budget_per_person = float(form["budget_per_person"]) if form.get("budget_per_person") else None
    guest_count = int(form["guest_count"]) if form.get("guest_count") else None

    db = get_db()
    qr = QuoteRequest(
        company_id=user.company_id,
        user_id=user.id,
        company_service_id=service_id,
        status=status,
        service_type=form.get("service_type") or None,
        meal_type=form.get("meal_type"),
        event_date=datetime.date.fromisoformat(form["event_date"]) if form.get("event_date") else None,
        guest_count=guest_count,
        event_address=form.get("event_address") or None,
        event_city=form.get("event_city") or None,
        event_zip_code=form.get("event_zip_code") or None,
        event_latitude=float(form["event_latitude"]) if form.get("event_latitude") else None,
        event_longitude=float(form["event_longitude"]) if form.get("event_longitude") else None,
        budget_global=budget_global,
        budget_per_person=budget_per_person,
        dietary_vegetarian=form.get("dietary_vegetarian") == "1",
        dietary_vegan=form.get("dietary_vegan") == "1",
        dietary_halal=form.get("dietary_halal") == "1",
        dietary_casher=form.get("dietary_casher") == "1",
        dietary_gluten_free=form.get("dietary_gluten_free") == "1",
        dietary_lactose_free=form.get("dietary_lactose_free") == "1",
        vegetarian_count=int(form["vegetarian_count"]) if form.get("vegetarian_count") else None,
        vegan_count=int(form["vegan_count"]) if form.get("vegan_count") else None,
        halal_count=int(form["halal_count"]) if form.get("halal_count") else None,
        casher_count=int(form["casher_count"]) if form.get("casher_count") else None,
        gluten_free_count=int(form["gluten_free_count"]) if form.get("gluten_free_count") else None,
        lactose_free_count=int(form["lactose_free_count"]) if form.get("lactose_free_count") else None,
        drinks_alcohol=form.get("drinks_alcohol") == "1",
        drinks_details=form.get("drinks_details") or None,
        wants_waitstaff=form.get("wants_waitstaff") == "1",
        service_waitstaff_details=form.get("service_waitstaff_details") or None,
        wants_equipment=form.get("wants_equipment") == "1",
        wants_decoration=form.get("wants_decoration") == "1",
        wants_setup=form.get("wants_setup") == "1",
        wants_cleanup=form.get("wants_cleanup") == "1",
        is_compare_mode=is_compare,
        message_to_caterer=form.get("message_to_caterer") or None,
    )
    db.add(qr)
    db.flush()
    qr_id = qr.id
    db.commit()

    flash("Votre demande de devis a ete envoyee avec succes.", "success")
    return redirect(url_for("client.request_detail", request_id=qr_id))


@client_bp.route("/requests/<uuid:request_id>")
@login_required
@role_required("client_admin", "client_user")
def request_detail(request_id):
    user = g.current_user
    db = get_db()
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        abort(404)

    qrcs = db.execute(
        select(QuoteRequestCaterer).where(
            QuoteRequestCaterer.quote_request_id == request_id
        )
    ).scalars().all()

    quotes = db.execute(
        select(Quote).where(Quote.quote_request_id == request_id)
        .order_by(Quote.created_at.asc())
    ).scalars().all()

    return render_template(
        "client/requests/detail.html",
        user=user,
        qr=qr,
        qrcs=qrcs,
        quotes=quotes,
        meal_type_labels=MEAL_TYPE_LABELS,
    )


@client_bp.route("/requests/<uuid:request_id>/accept-quote", methods=["POST"])
@login_required
@role_required("client_admin", "client_user")
def accept_quote(request_id):
    user = g.current_user
    quote_id = request.form.get("quote_id")
    if not quote_id:
        abort(400)

    db = get_db()
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        abort(404)

    accepted_quote = db.execute(
        select(Quote).where(
            Quote.id == uuid.UUID(quote_id),
            Quote.quote_request_id == request_id,
        )
    ).scalar_one_or_none()
    if not accepted_quote:
        abort(404)

    accepted_quote.status = QuoteStatus.accepted

    other_quotes = db.execute(
        select(Quote).where(
            Quote.quote_request_id == request_id,
            Quote.id != accepted_quote.id,
            Quote.status == QuoteStatus.sent,
        )
    ).scalars().all()
    for q in other_quotes:
        q.status = QuoteStatus.refused
        q.refusal_reason = "Un autre devis a ete accepte."

    order = Order(
        quote_id=accepted_quote.id,
        client_admin_id=user.id,
        status=OrderStatus.confirmed,
        delivery_date=qr.event_date,
        delivery_address=f"{qr.event_address}, {qr.event_zip_code} {qr.event_city}",
    )
    db.add(order)
    db.flush()

    qr.status = QuoteRequestStatus.completed
    order_id = order.id
    db.commit()

    flash("Devis accepte ! La commande a ete creee.", "success")
    return redirect(url_for("client.order_detail", order_id=order_id))


@client_bp.route("/requests/<uuid:request_id>/refuse-quote", methods=["POST"])
@login_required
@role_required("client_admin", "client_user")
def refuse_quote(request_id):
    user = g.current_user
    quote_id = request.form.get("quote_id")
    reason = request.form.get("refusal_reason", "")
    if not quote_id:
        abort(400)

    db = get_db()
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        abort(404)

    quote = db.execute(
        select(Quote).where(
            Quote.id == uuid.UUID(quote_id),
            Quote.quote_request_id == request_id,
        )
    ).scalar_one_or_none()
    if not quote:
        abort(404)

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

    db.commit()

    flash("Devis refuse.", "info")
    return redirect(url_for("client.request_detail", request_id=request_id))


@client_bp.route("/requests/<uuid:request_id>/edit", methods=["GET"])
@login_required
@role_required("client_admin", "client_user")
def request_edit(request_id):
    user = g.current_user
    db = get_db()
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        abort(404)
    if qr.status not in (QuoteRequestStatus.draft, QuoteRequestStatus.pending_review):
        flash("Cette demande ne peut plus etre modifiee.", "error")
        return redirect(url_for("client.request_detail", request_id=request_id))

    services = db.execute(
        select(CompanyService).where(CompanyService.company_id == user.company_id)
    ).scalars().all()

    return render_template(
        "client/requests/edit.html",
        user=user,
        qr=qr,
        services=services,
    )


@client_bp.route("/requests/<uuid:request_id>/edit", methods=["POST"])
@login_required
@role_required("client_admin", "client_user")
def request_edit_post(request_id):
    user = g.current_user
    form = request.form

    db = get_db()
    qr = db.execute(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id,
            QuoteRequest.company_id == user.company_id,
        )
    ).scalar_one_or_none()
    if not qr:
        abort(404)
    if qr.status not in (QuoteRequestStatus.draft, QuoteRequestStatus.pending_review):
        flash("Cette demande ne peut plus etre modifiee.", "error")
        return redirect(url_for("client.request_detail", request_id=request_id))

    service_id = form.get("company_service_id") or None
    if service_id:
        service_id = uuid.UUID(service_id)

    qr.company_service_id = service_id
    qr.service_type = form.get("service_type") or None
    qr.meal_type = form.get("meal_type")
    qr.event_date = datetime.date.fromisoformat(form["event_date"]) if form.get("event_date") else None
    qr.guest_count = int(form["guest_count"]) if form.get("guest_count") else None
    qr.event_address = form.get("event_address") or None
    qr.event_city = form.get("event_city") or None
    qr.event_zip_code = form.get("event_zip_code") or None
    qr.event_latitude = float(form["event_latitude"]) if form.get("event_latitude") else None
    qr.event_longitude = float(form["event_longitude"]) if form.get("event_longitude") else None
    qr.budget_global = float(form["budget_global"]) if form.get("budget_global") else None
    qr.budget_per_person = float(form["budget_per_person"]) if form.get("budget_per_person") else None
    qr.dietary_vegetarian = form.get("dietary_vegetarian") == "1"
    qr.dietary_vegan = form.get("dietary_vegan") == "1"
    qr.dietary_halal = form.get("dietary_halal") == "1"
    qr.dietary_casher = form.get("dietary_casher") == "1"
    qr.dietary_gluten_free = form.get("dietary_gluten_free") == "1"
    qr.dietary_lactose_free = form.get("dietary_lactose_free") == "1"
    qr.vegetarian_count = int(form["vegetarian_count"]) if form.get("vegetarian_count") else None
    qr.vegan_count = int(form["vegan_count"]) if form.get("vegan_count") else None
    qr.halal_count = int(form["halal_count"]) if form.get("halal_count") else None
    qr.casher_count = int(form["casher_count"]) if form.get("casher_count") else None
    qr.gluten_free_count = int(form["gluten_free_count"]) if form.get("gluten_free_count") else None
    qr.lactose_free_count = int(form["lactose_free_count"]) if form.get("lactose_free_count") else None
    qr.drinks_alcohol = form.get("drinks_alcohol") == "1"
    qr.drinks_details = form.get("drinks_details") or None
    qr.wants_waitstaff = form.get("wants_waitstaff") == "1"
    qr.service_waitstaff_details = form.get("service_waitstaff_details") or None
    qr.wants_equipment = form.get("wants_equipment") == "1"
    qr.wants_decoration = form.get("wants_decoration") == "1"
    qr.wants_setup = form.get("wants_setup") == "1"
    qr.wants_cleanup = form.get("wants_cleanup") == "1"
    qr.is_compare_mode = form.get("is_compare_mode") == "1"
    qr.message_to_caterer = form.get("message_to_caterer") or None

    is_compare = form.get("is_compare_mode") == "1"
    qr.status = QuoteRequestStatus.pending_review if is_compare else QuoteRequestStatus.sent_to_caterers

    db.commit()

    flash("Demande mise a jour.", "success")
    return redirect(url_for("client.request_detail", request_id=request_id))


@client_bp.route("/orders")
@login_required
@role_required("client_admin", "client_user")
def orders_list():
    user = g.current_user
    db = get_db()
    orders = db.execute(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
        .where(QuoteRequest.company_id == user.company_id)
        .order_by(Order.created_at.desc())
    ).scalars().all()
    return render_template(
        "client/orders/list.html",
        user=user,
        orders=orders,
        order_status_labels=ORDER_STATUS_LABELS,
    )


@client_bp.route("/orders/<uuid:order_id>")
@login_required
@role_required("client_admin", "client_user")
def order_detail(order_id):
    user = g.current_user
    db = get_db()
    order = db.execute(
        select(Order)
        .join(Quote, Order.quote_id == Quote.id)
        .join(QuoteRequest, Quote.quote_request_id == QuoteRequest.id)
        .where(Order.id == order_id, QuoteRequest.company_id == user.company_id)
    ).scalar_one_or_none()
    if not order:
        abort(404)
    return render_template(
        "client/orders/detail.html",
        user=user,
        order=order,
        order_status_labels=ORDER_STATUS_LABELS,
    )


@client_bp.route("/search")
@login_required
@role_required("client_admin", "client_user")
def search():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    structure_type = request.args.get("structure_type", "")
    dietary = request.args.getlist("dietary")
    capacity = request.args.get("capacity", type=int)
    service_type = request.args.get("service_type", "")

    db = get_db()
    stmt = select(Caterer).where(Caterer.is_validated.is_(True))

    if structure_type:
        if structure_type in STRUCTURE_GROUPS:
            stmt = stmt.where(Caterer.structure_type.in_(
                [t.value for t in STRUCTURE_GROUPS[structure_type]]
            ))
        else:
            stmt = stmt.where(Caterer.structure_type == structure_type)

    for flag in dietary:
        col = getattr(Caterer, f"dietary_{flag}", None)
        if col is not None:
            stmt = stmt.where(col.is_(True))

    if capacity:
        stmt = stmt.where(
            or_(Caterer.capacity_max.is_(None), Caterer.capacity_max >= capacity)
        )

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Caterer.name.ilike(pattern),
                Caterer.description.ilike(pattern),
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    total_pages = max(1, math.ceil(total / ITEMS_PER_PAGE))
    page = max(1, min(page, total_pages))

    caterers = db.scalars(
        stmt.order_by(Caterer.name)
        .offset((page - 1) * ITEMS_PER_PAGE)
        .limit(ITEMS_PER_PAGE)
    ).all()

    return render_template(
        "client/search.html",
        user=g.current_user,
        caterers=caterers,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
        structure_type=structure_type,
        dietary=dietary,
        capacity=capacity,
        service_type=service_type,
        dietary_flags=DIETARY_FLAGS,
        meal_type_labels=MEAL_TYPE_LABELS,
    )


@client_bp.route("/caterers/<uuid:caterer_id>")
@login_required
@role_required("client_admin", "client_user")
def caterer_detail(caterer_id):
    db = get_db()
    caterer = db.get(Caterer, caterer_id)
    if not caterer or not caterer.is_validated:
        abort(404)
    return render_template(
        "client/caterer_detail.html",
        user=g.current_user,
        caterer=caterer,
        dietary_flags=DIETARY_FLAGS,
        meal_type_labels=MEAL_TYPE_LABELS,
    )


@client_bp.route("/team")
@login_required
@role_required("client_admin")
def team():
    user = g.current_user
    db = get_db()
    services = db.scalars(
        select(CompanyService).where(CompanyService.company_id == user.company_id)
    ).all()
    employees = db.scalars(
        select(CompanyEmployee).where(CompanyEmployee.company_id == user.company_id)
    ).all()
    pending_users = db.scalars(
        select(User).where(
            User.company_id == user.company_id,
            User.membership_status == MembershipStatus.pending,
        )
    ).all()
    return render_template(
        "client/team.html",
        user=user,
        services=services,
        employees=employees,
        pending_users=pending_users,
    )


@client_bp.route("/team/services", methods=["POST"])
@login_required
@role_required("client_admin")
def team_service_create():
    user = g.current_user
    name = request.form.get("name", "").strip()
    if not name:
        flash("Le nom du service est obligatoire.", "error")
        return redirect(url_for("client.team"))
    db = get_db()
    service = CompanyService(
        company_id=user.company_id,
        name=name,
        description=request.form.get("description", "").strip() or None,
        annual_budget=float(request.form["annual_budget"]) if request.form.get("annual_budget") else None,
    )
    db.add(service)
    db.commit()
    flash("Service cree.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/services/<uuid:service_id>/edit", methods=["POST"])
@login_required
@role_required("client_admin")
def team_service_edit(service_id):
    user = g.current_user
    db = get_db()
    service = db.scalar(
        select(CompanyService).where(
            CompanyService.id == service_id,
            CompanyService.company_id == user.company_id,
        )
    )
    if not service:
        abort(404)
    service.name = request.form.get("name", service.name).strip()
    service.description = request.form.get("description", "").strip() or None
    service.annual_budget = float(request.form["annual_budget"]) if request.form.get("annual_budget") else None
    db.commit()
    flash("Service mis a jour.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/services/<uuid:service_id>/delete", methods=["POST"])
@login_required
@role_required("client_admin")
def team_service_delete(service_id):
    user = g.current_user
    db = get_db()
    service = db.scalar(
        select(CompanyService).where(
            CompanyService.id == service_id,
            CompanyService.company_id == user.company_id,
        )
    )
    if not service:
        abort(404)
    employee_count = db.scalar(
        select(func.count(CompanyEmployee.id)).where(CompanyEmployee.service_id == service_id)
    )
    if employee_count > 0:
        flash("Impossible de supprimer un service auquel des employes sont rattaches.", "error")
        return redirect(url_for("client.team"))
    db.delete(service)
    db.commit()
    flash("Service supprime.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/employees", methods=["POST"])
@login_required
@role_required("client_admin")
def team_employee_create():
    user = g.current_user
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    if not all([first_name, last_name, email]):
        flash("Prenom, nom et email sont obligatoires.", "error")
        return redirect(url_for("client.team"))
    service_id = uuid.UUID(request.form["service_id"]) if request.form.get("service_id") else None
    db = get_db()
    employee = CompanyEmployee(
        company_id=user.company_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        position=request.form.get("position", "").strip() or None,
        service_id=service_id,
    )
    db.add(employee)
    db.commit()
    flash("Employe ajoute.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/employees/<uuid:employee_id>/edit", methods=["POST"])
@login_required
@role_required("client_admin")
def team_employee_edit(employee_id):
    user = g.current_user
    db = get_db()
    employee = db.scalar(
        select(CompanyEmployee).where(
            CompanyEmployee.id == employee_id,
            CompanyEmployee.company_id == user.company_id,
        )
    )
    if not employee:
        abort(404)
    employee.first_name = request.form.get("first_name", employee.first_name).strip()
    employee.last_name = request.form.get("last_name", employee.last_name).strip()
    employee.email = request.form.get("email", employee.email).strip().lower()
    employee.position = request.form.get("position", "").strip() or None
    service_id = request.form.get("service_id")
    employee.service_id = uuid.UUID(service_id) if service_id else None
    db.commit()
    flash("Employe mis a jour.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/employees/<uuid:employee_id>/delete", methods=["POST"])
@login_required
@role_required("client_admin")
def team_employee_delete(employee_id):
    user = g.current_user
    db = get_db()
    employee = db.scalar(
        select(CompanyEmployee).where(
            CompanyEmployee.id == employee_id,
            CompanyEmployee.company_id == user.company_id,
        )
    )
    if not employee:
        abort(404)
    db.delete(employee)
    db.commit()
    flash("Employe supprime.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/employees/<uuid:employee_id>/invite", methods=["POST"])
@login_required
@role_required("client_admin")
def team_employee_invite(employee_id):
    user = g.current_user
    db = get_db()
    employee = db.scalar(
        select(CompanyEmployee).where(
            CompanyEmployee.id == employee_id,
            CompanyEmployee.company_id == user.company_id,
        )
    )
    if not employee:
        abort(404)
    employee.invited_at = datetime.datetime.utcnow()
    db.commit()
    flash(f"Invitation envoyee a {employee.email}.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/approve/<uuid:user_id>", methods=["POST"])
@login_required
@role_required("client_admin")
def team_approve(user_id):
    admin = g.current_user
    db = get_db()
    target_user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.company_id == admin.company_id,
            User.membership_status == MembershipStatus.pending,
        )
    )
    if not target_user:
        abort(404)
    target_user.membership_status = MembershipStatus.active
    db.commit()
    flash("Membre approuve.", "success")
    return redirect(url_for("client.team"))


@client_bp.route("/team/reject/<uuid:user_id>", methods=["POST"])
@login_required
@role_required("client_admin")
def team_reject(user_id):
    admin = g.current_user
    db = get_db()
    target_user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.company_id == admin.company_id,
            User.membership_status == MembershipStatus.pending,
        )
    )
    if not target_user:
        abort(404)
    target_user.membership_status = MembershipStatus.rejected
    db.commit()
    flash("Membre rejete.", "info")
    return redirect(url_for("client.team"))


@client_bp.route("/messages")
@login_required
@role_required("client_admin", "client_user")
def messages():
    user = g.current_user
    db = get_db()
    threads = _get_user_threads(db, user.id)
    return render_template("client/messages/list.html", user=user, threads=threads)


@client_bp.route("/messages/<uuid:thread_id>")
@login_required
@role_required("client_admin", "client_user")
def message_thread(thread_id):
    user = g.current_user
    db = get_db()
    first_msg = db.scalar(
        select(Message).where(
            Message.thread_id == thread_id,
            or_(Message.sender_id == user.id, Message.recipient_id == user.id),
        )
    )
    if not first_msg:
        abort(404)
    other_id = first_msg.recipient_id if first_msg.sender_id == user.id else first_msg.sender_id
    other_user = db.get(User, other_id)
    return render_template(
        "client/messages/thread.html",
        user=user,
        thread_id=thread_id,
        other_user=other_user,
    )


@client_bp.route("/profile", methods=["GET", "POST"])
@login_required
@role_required("client_admin", "client_user")
def profile():
    user = g.current_user
    if request.method == "POST":
        db = get_db()
        u = db.get(User, user.id)
        u.first_name = request.form.get("first_name", u.first_name).strip()
        u.last_name = request.form.get("last_name", u.last_name).strip()
        u.email = request.form.get("email", u.email).strip().lower()
        db.commit()
        flash("Profil mis a jour.", "success")
        return redirect(url_for("client.profile"))
    return render_template("client/profile.html", user=user)


@client_bp.route("/settings", methods=["GET", "POST"])
@login_required
@role_required("client_admin")
def settings():
    user = g.current_user
    if request.method == "POST":
        db = get_db()
        company = db.get(Company, user.company_id)
        company.name = request.form.get("name", company.name).strip()
        company.siret = request.form.get("siret", company.siret).strip()
        company.address = request.form.get("address", "").strip() or None
        company.city = request.form.get("city", "").strip() or None
        company.zip_code = request.form.get("zip_code", "").strip() or None
        company.oeth_eligible = request.form.get("oeth_eligible") == "1"
        company.budget_annual = float(request.form["budget_annual"]) if request.form.get("budget_annual") else None
        logo_file = request.files.get("logo")
        if logo_file:
            logo_url = save_upload(logo_file, subfolder="companies")
            if logo_url:
                company.logo_url = logo_url
        db.commit()
        flash("Parametres mis a jour.", "success")
        return redirect(url_for("client.settings"))
    db = get_db()
    company = db.get(Company, user.company_id)
    return render_template("client/settings.html", user=user, company=company)


def _get_user_threads(db, user_id):
    """Return thread summaries for a user, grouped by thread_id."""
    all_messages = db.scalars(
        select(Message)
        .where(or_(Message.sender_id == user_id, Message.recipient_id == user_id))
        .order_by(Message.created_at.desc())
    ).all()

    threads = {}
    for msg in all_messages:
        tid = str(msg.thread_id)
        if tid not in threads:
            other_id = msg.recipient_id if msg.sender_id == user_id else msg.sender_id
            other_user = db.get(User, other_id)
            unread = db.scalar(
                select(func.count(Message.id)).where(
                    Message.thread_id == msg.thread_id,
                    Message.recipient_id == user_id,
                    Message.is_read.is_(False),
                )
            )
            threads[tid] = {
                "thread_id": tid,
                "other_name": f"{other_user.first_name} {other_user.last_name}" if other_user else "Inconnu",
                "last_message": msg.body[:80],
                "last_at": msg.created_at,
                "unread": unread,
            }
    return list(threads.values())
