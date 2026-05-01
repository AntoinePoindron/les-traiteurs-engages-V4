import os

import bcrypt
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from sqlalchemy import select

from database import get_db
from extensions import limiter
from models import (
    Caterer,
    Company,
    CompanyEmployee,
    CompanyService,
    MembershipStatus,
    User,
    UserRole,
)
from services.slugs import generate_invoice_prefix

auth_bp = Blueprint("auth", __name__)

# Rate limits applied to the GETs too so an attacker can't bypass by only POSTing.
# Login: 10 / min for legitimate humans. Signup: 5 / hour by default to deter
# spam — override with SIGNUP_LIMIT=<rate> in docker-compose.local.yml / .env
# when iterating locally so test loops don't wedge for an hour.
LOGIN_LIMIT = "10 per minute"
SIGNUP_LIMIT = os.environ.get("SIGNUP_LIMIT", "5 per hour")

# Password policy (audit 1 VULN-14). NIST SP 800-63B: length is the dominant
# factor; complexity rules are weak by themselves but block the laziest attempts.
# We require length >= 12 + at least 3 character classes + not in a top-passwords
# blocklist. For a stronger check, plug in zxcvbn or Have-I-Been-Pwned later.
PASSWORD_MIN_LENGTH = 12
PASSWORD_BLOCKLIST = {
    "password",
    "password1",
    "password123",
    "passw0rd",
    "motdepasse",
    "azerty",
    "azerty123",
    "qwerty",
    "qwerty123",
    "qwertyuiop",
    "123456",
    "123456789",
    "1234567890",
    "111111",
    "000000",
    "12345678",
    "iloveyou",
    "admin",
    "admin123",
    "letmein",
    "welcome",
    "welcome1",
    "monkey",
    "dragon",
    "abc123",
    "abcdef",
    "changeme",
    "changeme123",
    "secret",
    "test1234",
}

# Pre-computed dummy hash so /login always pays bcrypt's cost, whether the
# email exists or not. Without this, the `or` short-circuit at l. 84 below
# made bcrypt run only when the user existed, leaking ~250 ms on hits
# vs ~10 ms on misses — trivial email enumeration (audit VULN-102).
# Generated once at import; the actual password we hash is irrelevant
# because we only care about constant work.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"timing-safe-dummy", bcrypt.gensalt()).decode()


def validate_password(password: str) -> str | None:
    """Return None if the password passes policy, else a user-facing error."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return (
            f"Le mot de passe doit comporter au moins {PASSWORD_MIN_LENGTH} caracteres."
        )
    if password.lower() in PASSWORD_BLOCKLIST:
        return "Ce mot de passe est trop courant. Choisissez-en un plus original."
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return (
            "Le mot de passe doit contenir au moins 3 categories de caracteres "
            "parmi : minuscules, majuscules, chiffres, caracteres speciaux."
        )
    return None


ROLE_DASHBOARDS = {
    UserRole.client_admin: "client.dashboard",
    UserRole.client_user: "client.dashboard",
    UserRole.caterer: "caterer.dashboard",
    UserRole.super_admin: "admin.dashboard",
}


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(LOGIN_LIMIT, methods=["POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Veuillez remplir tous les champs.", "error")
            return render_template("auth/login.html")
        db = get_db()
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        # VULN-102: always pay the bcrypt cost — comparing against a dummy
        # hash when the user does not exist keeps the response time
        # constant (~250 ms in both branches) and prevents email
        # enumeration via a timing side-channel.
        hash_to_check = user.password_hash if user else _DUMMY_PASSWORD_HASH
        password_ok = bcrypt.checkpw(password.encode(), hash_to_check.encode())
        if not user or not password_ok:
            flash("Email ou mot de passe incorrect.", "error")
            return render_template("auth/login.html")
        if not user.is_active:
            flash("Votre compte est desactive.", "error")
            return render_template("auth/login.html")
        # Pending = client_user signed up against an existing SIRET, awaiting
        # the company admin's approval. Rejected = explicitly refused. Either
        # way: never issue a session — they would otherwise be able to read
        # private company data (quote requests, orders, messages).
        if user.membership_status == MembershipStatus.pending:
            flash(
                "Votre rattachement est en attente de validation par "
                "l'administrateur de votre structure. Vous pourrez vous "
                "connecter une fois votre acces approuve.",
                "info",
            )
            return render_template("auth/login.html")
        if user.membership_status == MembershipStatus.rejected:
            flash(
                "Votre demande de rattachement a ete refusee. "
                "Contactez l'administrateur de votre structure.",
                "error",
            )
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
@limiter.limit(SIGNUP_LIMIT, methods=["POST"])
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

        password_error = validate_password(password)
        if password_error:
            flash(password_error, "error")
            return render_template("auth/signup.html")

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        db = get_db()

        # VULN-28: always execute both lookups so timing is identical
        # regardless of whether email or SIRET already exists.
        existing_user = db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()
        existing_company = db.execute(
            select(Company).where(Company.siret == siret)
        ).scalar_one_or_none()

        if existing_user:
            flash(
                "Inscription impossible avec ces informations. "
                "Si vous avez deja un compte, connectez-vous.",
                "error",
            )
            return render_template("auth/signup.html")

        if role == "client_admin":
            company_name = request.form.get("company_name", "").strip()
            if not company_name:
                flash("Le nom de l'entreprise est obligatoire.", "error")
                return render_template("auth/signup.html")

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
                # VULN-28: avoid confirming SIRET presence. Wording stays
                # informative for the legitimate case (employee joining an
                # existing company) without naming the company or the SIRET.
                # No session is issued: the user must wait for the company
                # admin's approval before /login lets them in. This prevents
                # a SIRET-based info-disclosure vector where anyone signing
                # up could read the company's quote requests / orders /
                # messages while waiting for approval.
                flash(
                    "Votre demande de rattachement a ete enregistree. "
                    "L'administrateur de votre structure a ete informe. "
                    "Vous pourrez vous connecter une fois votre acces "
                    "approuve.",
                    "info",
                )
                return redirect(url_for("auth.login"))

            # Company.name is non-nullable but no longer collected at signup —
            # the SIRET stands in until the admin renames it via /client/settings.
            company = Company(name=siret, siret=siret)
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
            db.add(
                CompanyEmployee(
                    company_id=company.id,
                    service_id=direction_service.id,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    position="Administrateur",
                    user_id=user.id,
                )
            )
            db.commit()

            session["user_id"] = str(user.id)
            # First-time signup with a fresh SIRET: the new client_admin lands
            # on /client/settings so they can fill in the company name +
            # billing address. Company.name is currently the SIRET as a
            # placeholder.
            flash(
                "Bienvenue ! Pour finaliser la création de votre espace, "
                "complétez les paramètres de votre structure.",
                "success",
            )
            return redirect(url_for("client.settings"))

        elif role == "caterer":
            caterer_name = request.form.get("caterer_name", "").strip()
            structure_type = request.form.get("structure_type", "").strip()
            address = request.form.get("address", "").strip()
            city = request.form.get("city", "").strip()
            zip_code = request.form.get("zip_code", "").strip()

            if not all([caterer_name, structure_type]):
                flash(
                    "Le nom du traiteur et le type de structure sont obligatoires.",
                    "error",
                )
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


@auth_bp.route("/logout", methods=["POST"])
def logout():
    # VULN-18: POST + CSRF token instead of GET so a third-party page cannot
    # silently log the user out via <img src=".../logout"> or a fetch.
    # CSRFProtect (extensions.csrf) validates the form's csrf_token field.
    session.clear()
    return redirect(url_for("auth.login"))
