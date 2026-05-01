import datetime

from flask import flash, g, redirect, render_template, url_for
from sqlalchemy import func, select

from blueprints.client._helpers import own_service_id
from blueprints.middleware import login_required, role_required
from blueprints.scoping import (
    get_company_employee,
    get_company_service,
    get_pending_user,
)
from database import get_db
from forms.client import EmployeeForm, ServiceForm
from models import Company, CompanyEmployee, CompanyService, MembershipStatus, User
from services.notifications import notify


def register(bp):
    @bp.route("/team")
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

    @bp.route("/team/services", methods=["POST"])
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

    @bp.route("/team/services/<uuid:service_id>/edit", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_service_edit(service_id):
        user = g.current_user
        db = get_db()
        service = get_company_service(service_id, user.company_id)
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

    @bp.route("/team/services/<uuid:service_id>/delete", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_service_delete(service_id):
        user = g.current_user
        db = get_db()
        service = get_company_service(service_id, user.company_id)
        employee_count = db.scalar(
            select(func.count(CompanyEmployee.id)).where(
                CompanyEmployee.service_id == service_id
            )
        )
        if employee_count > 0:
            flash(
                "Impossible de supprimer un service auquel des employes sont rattaches.",
                "error",
            )
            return redirect(url_for("client.team"))
        db.delete(service)
        db.commit()
        flash("Service supprime.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/employees", methods=["POST"])
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
            service_id=own_service_id(db, user, form.service_id.data),
        )
        db.add(employee)
        db.commit()
        flash("Employe ajoute.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/employees/<uuid:employee_id>/edit", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_employee_edit(employee_id):
        user = g.current_user
        db = get_db()
        employee = get_company_employee(employee_id, user.company_id)
        form = EmployeeForm()
        if not form.validate_on_submit():
            flash("Prenom, nom et email sont obligatoires.", "error")
            return redirect(url_for("client.team"))
        employee.first_name = form.first_name.data.strip()
        employee.last_name = form.last_name.data.strip()
        employee.email = form.email.data.strip().lower()
        employee.position = (form.position.data or "").strip() or None
        employee.service_id = own_service_id(db, user, form.service_id.data)
        db.commit()
        flash("Employe mis a jour.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/employees/<uuid:employee_id>/delete", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_employee_delete(employee_id):
        user = g.current_user
        db = get_db()
        employee = get_company_employee(employee_id, user.company_id)
        db.delete(employee)
        db.commit()
        flash("Employe supprime.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/employees/<uuid:employee_id>/invite", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_employee_invite(employee_id):
        user = g.current_user
        db = get_db()
        employee = get_company_employee(employee_id, user.company_id)
        employee.invited_at = datetime.datetime.utcnow()
        db.commit()
        flash(f"Invitation envoyee a {employee.email}.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/approve/<uuid:user_id>", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_approve(user_id):
        admin = g.current_user
        db = get_db()
        target_user = get_pending_user(user_id, admin.company_id)
        target_user.membership_status = MembershipStatus.active

        # Approval = "this person works here", so they should appear in
        # the effectifs list. If the admin had pre-created an invite row
        # with the same email, link it to the user instead of duplicating
        # the entry.
        existing = db.scalar(
            select(CompanyEmployee).where(
                CompanyEmployee.company_id == admin.company_id,
                (
                    (CompanyEmployee.user_id == target_user.id)
                    | (CompanyEmployee.email == target_user.email)
                ),
            )
        )
        if existing:
            existing.user_id = target_user.id
            existing.first_name = target_user.first_name
            existing.last_name = target_user.last_name
            existing.email = target_user.email
        else:
            db.add(
                CompanyEmployee(
                    company_id=admin.company_id,
                    first_name=target_user.first_name,
                    last_name=target_user.last_name,
                    email=target_user.email,
                    user_id=target_user.id,
                )
            )

        # Tell the freshly-approved user. They couldn't log in until
        # now, so the notification will pop on their first session.
        company = db.get(Company, admin.company_id)
        notify(
            db,
            user_id=target_user.id,
            type="membership_approved",
            title="Bienvenue !",
            body=f"Votre rattachement à {company.name if company else 'votre structure'} a été validé.",
            related_entity_type="company",
            related_entity_id=admin.company_id,
        )

        db.commit()
        flash("Membre approuve et ajoute aux effectifs.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/reject/<uuid:user_id>", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_reject(user_id):
        admin = g.current_user
        db = get_db()
        target_user = get_pending_user(user_id, admin.company_id)
        target_user.membership_status = MembershipStatus.rejected
        db.commit()
        flash("Membre rejete.", "info")
        return redirect(url_for("client.team"))
