import bcrypt
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import select

from database import get_db
from models import Caterer, Company, CompanyEmployee, CompanyService, MembershipStatus, User, UserRole
from services.slugs import generate_invoice_prefix

auth_bp = Blueprint("auth", __name__)

ROLE_DASHBOARDS = {
    UserRole.client_admin: "client.dashboard",
    UserRole.client_user: "client.dashboard",
    UserRole.caterer: "caterer.dashboard",
    UserRole.super_admin: "admin.dashboard",
}


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Veuillez remplir tous les champs.", "error")
            return render_template("auth/login.html")
        db = get_db()
        user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            flash("Email ou mot de passe incorrect.", "error")
            return render_template("auth/login.html")
        if not user.is_active:
            flash("Votre compte est desactive.", "error")
            return render_template("auth/login.html")
        # Rotate session on successful auth: drop any pre-login state
        # (CSRF token, anonymous flash) before issuing the authenticated cookie.
        session.clear()
        session["user_id"] = str(user.id)
        session.permanent = True
        endpoint = ROLE_DASHBOARDS.get(UserRole(user.role), "client.dashboard")
        return redirect(url_for(endpoint))
    return render_template("auth/login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        role = request.form.get("role", "")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        siret = request.form.get("siret", "").strip()

        if not all([role, email, password, first_name, last_name, siret]):
            flash("Veuillez remplir tous les champs obligatoires.", "error")
            return render_template("auth/signup.html")

        if len(siret) != 14 or not siret.isdigit():
            flash("Le SIRET doit comporter exactement 14 chiffres.", "error")
            return render_template("auth/signup.html")

        if len(password) < 8:
            flash("Le mot de passe doit comporter au moins 8 caracteres.", "error")
            return render_template("auth/signup.html")

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        db = get_db()
        existing_user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        if existing_user:
            flash("Un compte avec cet email existe deja.", "error")
            return render_template("auth/signup.html")

        if role == "client_admin":
            company_name = request.form.get("company_name", "").strip()
            if not company_name:
                flash("Le nom de l'entreprise est obligatoire.", "error")
                return render_template("auth/signup.html")

            existing_company = db.execute(
                select(Company).where(Company.siret == siret)
            ).scalar_one_or_none()

            if existing_company:
                user = User(
                    email=email,
                    password_hash=password_hash,
                    first_name=first_name,
                    last_name=last_name,
                    role=UserRole.client_user,
                    company_id=existing_company.id,
                    membership_status=MembershipStatus.pending,
                )
                db.add(user)
                db.flush()
                db.commit()
                session["user_id"] = str(user.id)
                flash(
                    "Une entreprise avec ce SIRET existe deja. "
                    "Votre demande d'adhesion est en attente d'approbation.",
                    "info",
                )
                return redirect(url_for("client.dashboard"))

            company = Company(name=company_name, siret=siret)
            db.add(company)
            db.flush()
            user = User(
                email=email,
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.client_admin,
                company_id=company.id,
                membership_status=MembershipStatus.active,
            )
            db.add(user)
            db.flush()

            direction_service = CompanyService(
                company_id=company.id,
                name="Direction",
            )
            db.add(direction_service)
            db.flush()
            db.add(CompanyEmployee(
                company_id=company.id,
                service_id=direction_service.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                position="Administrateur",
                user_id=user.id,
            ))
            db.commit()

            session["user_id"] = str(user.id)
            flash("Votre compte entreprise a ete cree avec succes.", "success")
            return redirect(url_for("client.dashboard"))

        elif role == "caterer":
            caterer_name = request.form.get("caterer_name", "").strip()
            structure_type = request.form.get("structure_type", "").strip()
            address = request.form.get("address", "").strip()
            city = request.form.get("city", "").strip()
            zip_code = request.form.get("zip_code", "").strip()

            if not all([caterer_name, structure_type]):
                flash("Le nom du traiteur et le type de structure sont obligatoires.", "error")
                return render_template("auth/signup.html")

            invoice_prefix = generate_invoice_prefix(db)
            caterer = Caterer(
                name=caterer_name,
                siret=siret,
                structure_type=structure_type,
                address=address or None,
                city=city or None,
                zip_code=zip_code or None,
                invoice_prefix=invoice_prefix,
            )
            db.add(caterer)
            db.flush()
            user = User(
                email=email,
                password_hash=password_hash,
                first_name=first_name,
                last_name=last_name,
                role=UserRole.caterer,
                caterer_id=caterer.id,
                membership_status=MembershipStatus.active,
            )
            db.add(user)
            db.flush()
            db.commit()
            session["user_id"] = str(user.id)
            flash("Votre compte traiteur a ete cree avec succes.", "success")
            return redirect(url_for("caterer.dashboard"))

        else:
            flash("Type de compte invalide.", "error")
            return render_template("auth/signup.html")

    return render_template("auth/signup.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
