import datetime

from flask import abort, flash, g, redirect, render_template, url_for
from sqlalchemy import func, select

from blueprints.client._helpers import own_service_id
from blueprints.middleware import login_required, role_required
from database import get_db
from forms.client import EmployeeForm, ServiceForm
from models import CompanyEmployee, CompanyService, MembershipStatus, User


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

    @bp.route("/team/services/<uuid:service_id>/delete", methods=["POST"])
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

    @bp.route("/team/employees/<uuid:employee_id>/invite", methods=["POST"])
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

    @bp.route("/team/approve/<uuid:user_id>", methods=["POST"])
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

    @bp.route("/team/reject/<uuid:user_id>", methods=["POST"])
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
