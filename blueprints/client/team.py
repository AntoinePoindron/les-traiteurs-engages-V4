import datetime
import secrets
import uuid

from flask import flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, select


# Invite-link token lifetime. After this delay the token is considered
# expired even if it's still in the DB; /signup/invite/<token> rejects it.
INVITE_TOKEN_TTL_DAYS = 7

from blueprints.client._helpers import own_service_id
from blueprints.middleware import login_required, role_required
from blueprints.scoping import (
    get_company_employee,
    get_company_service,
    get_pending_user,
)
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

        # `?invite=<employee_id>` is set by the redirect after a fresh
        # collaborator creation — surfaces the generated invite link in
        # an auto-opened modal so the admin can copy/paste it
        # immediately. Only honoured when the employee belongs to the
        # admin's company and still has an active invite token.
        invite_employee = None
        invite_id = request.args.get("invite")
        if invite_id:
            try:
                invite_uuid = uuid.UUID(invite_id)
            except ValueError:
                invite_uuid = None
            if invite_uuid is not None:
                invite_employee = db.scalar(
                    select(CompanyEmployee).where(
                        CompanyEmployee.id == invite_uuid,
                        CompanyEmployee.company_id == user.company_id,
                        CompanyEmployee.invite_token.is_not(None),
                        CompanyEmployee.user_id.is_(None),
                    )
                )

        return render_template(
            "client/team.html",
            user=user,
            services=services,
            employees=employees,
            pending_users=pending_users,
            invite_employee=invite_employee,
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
        """Adding a collaborator implicitly invites them: an invite_token
        is generated at creation so the admin lands back on /client/team
        with the link displayed in an auto-opened modal (the only way
        for now to share access without an email pipeline)."""
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
            invite_token=secrets.token_urlsafe(32),
            invited_at=datetime.datetime.utcnow(),
        )
        db.add(employee)
        db.commit()
        # Redirect with the employee id in the query so /team can detect
        # it and pop the « lien d'invitation » modal.
        return redirect(url_for("client.team", invite=str(employee.id)))

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
        # Defense-in-depth for the disabled trash button on the team page:
        # an admin must not be able to remove their own effectifs row, even
        # by replaying the POST manually. The UI already hides the form
        # when employee.user_id == current user.
        if employee.user_id == user.id:
            flash("Vous ne pouvez pas vous retirer vous-même des effectifs.", "error")
            return redirect(url_for("client.team"))
        db.delete(employee)
        db.commit()
        flash("Employe supprime.", "success")
        return redirect(url_for("client.team"))

    @bp.route("/team/employees/<uuid:employee_id>/invite", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_employee_invite(employee_id):
        """Generate a single-use signup link the admin copies to send
        manually (no mail provider yet). Re-invoking on the same employee
        rotates the token — useful if the previous link was leaked or if
        the admin lost the URL."""
        user = g.current_user
        db = get_db()
        employee = get_company_employee(employee_id, user.company_id)
        if employee.user_id is not None:
            flash(
                "Ce collaborateur a deja un compte; aucune invitation necessaire.",
                "info",
            )
            return redirect(url_for("client.team"))
        # 32 bytes urlsafe = 43 chars, ~256 bits — unguessable.
        employee.invite_token = secrets.token_urlsafe(32)
        employee.invited_at = datetime.datetime.utcnow()
        db.commit()
        flash(
            "Lien d'invitation genere. Copiez-le et envoyez-le a votre collaborateur.",
            "success",
        )
        return redirect(url_for("client.team"))

    @bp.route("/team/employees/<uuid:employee_id>/invite/revoke", methods=["POST"])
    @login_required
    @role_required("client_admin")
    def team_employee_invite_revoke(employee_id):
        """Invalidate an outstanding invite link without rotating it
        (admin changed their mind, the address was wrong, …)."""
        user = g.current_user
        db = get_db()
        employee = get_company_employee(employee_id, user.company_id)
        employee.invite_token = None
        employee.invited_at = None
        db.commit()
        flash("Invitation revoquee.", "info")
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
