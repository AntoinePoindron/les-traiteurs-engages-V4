import datetime
import math
import uuid

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.client import (
    CompanySettingsForm,
    EmployeeForm,
    QuoteAcceptForm,
    QuoteRefuseForm,
    QuoteRequestForm,
    ServiceForm,
    UserProfileForm,
)
from services import workflow
from services.uploads import save_upload
from models import (
    MEAL_TYPE_LABELS,
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


def _own_service_id(db, user, raw):
    """Return the parsed UUID iff it names a CompanyService owned by `user`.

    Closes an IDOR-style FK reference: WTForms only validates UUID syntax,
    not that the row exists in the user's scope. Without this, a client
    could attach a quote_request or employee to another company's service.
    """
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

client_bp = Blueprint("client", __name__, url_prefix="/client")

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
    form = QuoteRequestForm()
    if not form.validate_on_submit():
        flash("Veuillez corriger les erreurs du formulaire.", "error")
        db = get_db()
        services = db.execute(
            select(CompanyService).where(CompanyService.company_id == user.company_id)
        ).scalars().all()
        return render_template("client/requests/new.html", user=user, services=services), 400

    db = get_db()
    service_id = _own_service_id(db, user, form.company_service_id.data)

    is_compare = form.is_compare_mode.data
    status = QuoteRequestStatus.pending_review if is_compare else QuoteRequestStatus.sent_to_caterers

    qr = QuoteRequest(
        company_id=user.company_id,
        user_id=user.id,
        company_service_id=service_id,
        status=status,
        service_type=form.service_type.data or None,
        meal_type=form.meal_type.data or None,
        event_date=form.event_date.data,
        guest_count=form.guest_count.data,
        event_address=form.event_address.data or None,
        event_city=form.event_city.data or None,
        event_zip_code=form.event_zip_code.data or None,
        event_latitude=form.event_latitude.data,
        event_longitude=form.event_longitude.data,
        budget_global=form.budget_global.data,
        budget_per_person=form.budget_per_person.data,
        dietary_vegetarian=form.dietary_vegetarian.data,
        dietary_vegan=form.dietary_vegan.data,
        dietary_halal=form.dietary_halal.data,
        dietary_casher=form.dietary_casher.data,
        dietary_gluten_free=form.dietary_gluten_free.data,
        dietary_lactose_free=form.dietary_lactose_free.data,
        vegetarian_count=form.vegetarian_count.data,
        vegan_count=form.vegan_count.data,
        halal_count=form.halal_count.data,
        casher_count=form.casher_count.data,
        gluten_free_count=form.gluten_free_count.data,
        lactose_free_count=form.lactose_free_count.data,
        drinks_alcohol=form.drinks_alcohol.data,
        drinks_details=form.drinks_details.data or None,
        wants_waitstaff=form.wants_waitstaff.data,
        service_waitstaff_details=form.service_waitstaff_details.data or None,
        wants_equipment=form.wants_equipment.data,
        wants_decoration=form.wants_decoration.data,
        wants_setup=form.wants_setup.data,
        wants_cleanup=form.wants_cleanup.data,
        is_compare_mode=is_compare,
        message_to_caterer=form.message_to_caterer.data or None,
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
    form = QuoteAcceptForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        quote_uuid = uuid.UUID(form.quote_id.data)
    except ValueError:
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

    # Only the caterer's own `sent` quotes can be accepted. Without this
    # filter a client (or a pre-fix-#4 pending user) could "accept" a
    # draft, refused, or long-expired quote — creating an Order the
    # caterer never committed to. Audit finding #5 (2026-04-24).
    accepted_quote = db.execute(
        select(Quote).where(
            Quote.id == quote_uuid,
            Quote.quote_request_id == request_id,
            Quote.status == QuoteStatus.sent,
        )
    ).scalar_one_or_none()
    if not accepted_quote:
        flash("Ce devis n'est plus disponible.", "error")
        return redirect(url_for("client.request_detail", request_id=request_id))

    if accepted_quote.valid_until and accepted_quote.valid_until < datetime.date.today():
        flash("Ce devis a expire.", "error")
        return redirect(url_for("client.request_detail", request_id=request_id))

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
    form = QuoteRefuseForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        quote_uuid = uuid.UUID(form.quote_id.data)
    except ValueError:
        abort(400)

    db = get_db()
    try:
        workflow.refuse_quote(
            db,
            request_id=request_id,
            quote_id=quote_uuid,
            user=g.current_user,
            reason=form.refusal_reason.data or None,
        )
    except (workflow.RequestNotFound, workflow.QuoteNotFound):
        abort(404)
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

    form = QuoteRequestForm()
    if not form.validate_on_submit():
        flash("Veuillez corriger les erreurs du formulaire.", "error")
        services = db.execute(
            select(CompanyService).where(CompanyService.company_id == user.company_id)
        ).scalars().all()
        return render_template(
            "client/requests/edit.html",
            user=user,
            qr=qr,
            services=services,
        ), 400

    qr.company_service_id = _own_service_id(db, user, form.company_service_id.data)
    qr.service_type = form.service_type.data or None
    qr.meal_type = form.meal_type.data or None
    qr.event_date = form.event_date.data
    qr.guest_count = form.guest_count.data
    qr.event_address = form.event_address.data or None
    qr.event_city = form.event_city.data or None
    qr.event_zip_code = form.event_zip_code.data or None
    qr.event_latitude = form.event_latitude.data
    qr.event_longitude = form.event_longitude.data
    qr.budget_global = form.budget_global.data
    qr.budget_per_person = form.budget_per_person.data
    qr.dietary_vegetarian = form.dietary_vegetarian.data
    qr.dietary_vegan = form.dietary_vegan.data
    qr.dietary_halal = form.dietary_halal.data
    qr.dietary_casher = form.dietary_casher.data
    qr.dietary_gluten_free = form.dietary_gluten_free.data
    qr.dietary_lactose_free = form.dietary_lactose_free.data
    qr.vegetarian_count = form.vegetarian_count.data
    qr.vegan_count = form.vegan_count.data
    qr.halal_count = form.halal_count.data
    qr.casher_count = form.casher_count.data
    qr.gluten_free_count = form.gluten_free_count.data
    qr.lactose_free_count = form.lactose_free_count.data
    qr.drinks_alcohol = form.drinks_alcohol.data
    qr.drinks_details = form.drinks_details.data or None
    qr.wants_waitstaff = form.wants_waitstaff.data
    qr.service_waitstaff_details = form.service_waitstaff_details.data or None
    qr.wants_equipment = form.wants_equipment.data
    qr.wants_decoration = form.wants_decoration.data
    qr.wants_setup = form.wants_setup.data
    qr.wants_cleanup = form.wants_cleanup.data
    qr.is_compare_mode = form.is_compare_mode.data
    qr.message_to_caterer = form.message_to_caterer.data or None

    qr.status = QuoteRequestStatus.pending_review if form.is_compare_mode.data else QuoteRequestStatus.sent_to_caterers

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
    form = ServiceForm()
    if not form.validate_on_submit():
        flash("Le nom du service est obligatoire.", "error")
        return redirect(url_for("client.team"))
    db = get_db()
    service = CompanyService(
        company_id=user.company_id,
        name=form.name.data.strip(),
        description=(form.description.data or "").strip() or None,
        annual_budget=form.annual_budget.data,
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
    form = ServiceForm()
    if not form.validate_on_submit():
        flash("Le nom du service est obligatoire.", "error")
        return redirect(url_for("client.team"))
    service.name = form.name.data.strip()
    service.description = (form.description.data or "").strip() or None
    service.annual_budget = form.annual_budget.data
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
    form = EmployeeForm()
    if not form.validate_on_submit():
        flash("Prenom, nom et email sont obligatoires.", "error")
        return redirect(url_for("client.team"))
    db = get_db()
    employee = CompanyEmployee(
        company_id=user.company_id,
        first_name=form.first_name.data.strip(),
        last_name=form.last_name.data.strip(),
        email=form.email.data.strip().lower(),
        position=(form.position.data or "").strip() or None,
        service_id=_own_service_id(db, user, form.service_id.data),
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
    form = EmployeeForm()
    if not form.validate_on_submit():
        flash("Prenom, nom et email sont obligatoires.", "error")
        return redirect(url_for("client.team"))
    employee.first_name = form.first_name.data.strip()
    employee.last_name = form.last_name.data.strip()
    employee.email = form.email.data.strip().lower()
    employee.position = (form.position.data or "").strip() or None
    employee.service_id = _own_service_id(db, user, form.service_id.data)
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
        form = UserProfileForm()
        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            return render_template("client/profile.html", user=user), 400
        db = get_db()
        u = db.get(User, user.id)
        if form.first_name.data is not None:
            u.first_name = (form.first_name.data or "").strip() or u.first_name
        if form.last_name.data is not None:
            u.last_name = (form.last_name.data or "").strip() or u.last_name
        if form.email.data:
            u.email = form.email.data.strip().lower()
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
        form = CompanySettingsForm()
        db = get_db()
        company = db.get(Company, user.company_id)
        if not form.validate_on_submit():
            flash("Veuillez corriger les erreurs du formulaire.", "error")
            return render_template("client/settings.html", user=user, company=company), 400
        if form.name.data is not None:
            company.name = (form.name.data or "").strip() or company.name
        if form.siret.data is not None:
            company.siret = (form.siret.data or "").strip() or company.siret
        company.address = (form.address.data or "").strip() or None
        company.city = (form.city.data or "").strip() or None
        company.zip_code = (form.zip_code.data or "").strip() or None
        company.oeth_eligible = form.oeth_eligible.data
        company.budget_annual = form.budget_annual.data
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
