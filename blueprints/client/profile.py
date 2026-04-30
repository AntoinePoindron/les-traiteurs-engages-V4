import bcrypt
from flask import flash, g, redirect, render_template, request, url_for

from blueprints.middleware import login_required, role_required
from database import get_db
from forms.client import CompanySettingsForm, UserProfileForm
from models import Company, User
from services.uploads import save_upload


def register(bp):
    @bp.route("/profile", methods=["GET", "POST"])
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
            new_email = (form.email.data or "").strip().lower()
            if new_email and new_email != u.email:
                pwd = form.current_password.data or ""
                if not pwd or not bcrypt.checkpw(pwd.encode(), u.password_hash.encode()):
                    flash("Mot de passe actuel incorrect. Le changement d'email necessite une re-authentification.", "error")
                    return render_template("client/profile.html", user=user), 400
                u.email = new_email
            db.commit()
            flash("Profil mis a jour.", "success")
            return redirect(url_for("client.profile"))
        return render_template("client/profile.html", user=user)

    @bp.route("/settings", methods=["GET", "POST"])
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
