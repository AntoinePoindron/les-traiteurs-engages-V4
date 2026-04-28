from datetime import timedelta

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from config import settings
from database import ScopedSession, get_db
from extensions import csrf, limiter
from logging_config import configure_logging, install_request_id_hooks
from models import (
    Caterer, Company, MembershipStatus, Order, OrderStatus, PaymentStatus,
    QRCStatus, QuoteRequestStatus, QuoteStatus, User, UserRole,
)

# A non-active membership status should not authorize action. Only users
# approved by a client_admin (or users whose role does not use the
# membership flow) are loaded as the current user. Audit finding #4.
_BLOCKED_MEMBERSHIP_STATUSES = {MembershipStatus.pending, MembershipStatus.rejected}

configure_logging()


CSP = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY

    if settings.trust_proxy_headers:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.secure_cookies,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        WTF_CSRF_TIME_LIMIT=None,  # token lives for the session lifetime
        # Cap request body size to defuse trivial DoS via huge uploads.
        # 16 MB covers logos, profile pictures, attachment screenshots
        # comfortably; bump if the product ever needs to accept invoice PDFs
        # or video. Triggers a 413 error caught by the handler below. (P2 #2)
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )

    csrf.init_app(app)
    limiter.init_app(app)
    install_request_id_hooks(app)

    app.jinja_env.globals.update(
        OrderStatus=OrderStatus,
        PaymentStatus=PaymentStatus,
        QuoteRequestStatus=QuoteRequestStatus,
        QuoteStatus=QuoteStatus,
        QRCStatus=QRCStatus,
        MembershipStatus=MembershipStatus,
        UserRole=UserRole,
    )

    from blueprints.admin import admin_bp
    from blueprints.api import api_bp
    from blueprints.auth import auth_bp
    from blueprints.caterer import caterer_bp
    from blueprints.client import client_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(caterer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    # Dev-only account switcher. Tied to the same env flag that seeds the
    # demo data so production (where the flag is empty) never registers
    # the route. See blueprints/devtools.py for the safety rationale.
    import os
    demo_mode = os.getenv("ENABLE_DEMO_SEED") == "1"
    if demo_mode:
        from blueprints.devtools import devtools_bp, DEMO_ACCOUNTS
        app.register_blueprint(devtools_bp)
    else:
        DEMO_ACCOUNTS = []

    @app.context_processor
    def _inject_demo_state():
        return {
            "dev_demo_mode": demo_mode,
            "dev_demo_accounts": DEMO_ACCOUNTS,
        }

    # CLI for ops tasks: `flask admin create / reset-password / list / disable`.
    # Avoids relying on ADMIN_INITIAL_PASSWORD env var for day-to-day admin
    # lifecycle (P3.2).
    from cli import admin_cli
    app.cli.add_command(admin_cli)

    @app.before_request
    def load_current_user():
        g.current_user = None
        if request.endpoint and (
            request.endpoint in ("static", "health")
            or (request.blueprint == "auth")
        ):
            return
        user_id = session.get("user_id")
        if user_id:
            db = get_db()
            user = db.execute(
                select(User).where(User.id == user_id)
            ).scalar_one_or_none()
            # Refuse to authenticate users whose membership isn't active:
            # signup-against-existing-SIRET creates pending users with a live
            # session, and nothing else gates on membership_status before
            # role-protected routes are hit.
            if user and user.membership_status in _BLOCKED_MEMBERSHIP_STATUSES:
                user = None
            g.current_user = user

    @app.teardown_appcontext
    def remove_session(exc=None):
        ScopedSession.remove()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = CSP
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(404)
    def _not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def _server_error(_e):
        # A DB error leaves the SQLAlchemy session in PendingRollbackError —
        # any subsequent ORM access (e.g. base.html dereferencing g.current_user)
        # raises again. Reset the session so the error template renders cleanly.
        try:
            ScopedSession.rollback()
        except Exception:
            pass
        return render_template("errors/500.html"), 500

    @app.errorhandler(ValueError)
    def _bad_value(e):
        # Defence in depth (audit 1 VULN-47, audit 2 #11): even though every
        # endpoint routes user input through WTForms or guarded try/except, a
        # future regression that lets ValueError escape would otherwise return
        # 500 with a stack trace in dev mode. Catch it here and return a clean
        # 400, in JSON for /api routes so the frontend can display it.
        if request.path.startswith("/api/"):
            return jsonify({"error": "Donnee invalide."}), 400
        return render_template("errors/400.html"), 400

    @app.errorhandler(413)
    def _too_large(_e):
        # Triggered when the request body exceeds MAX_CONTENT_LENGTH.
        if request.path.startswith("/api/"):
            return jsonify({"error": "Requete trop volumineuse (max 16 Mo)."}), 413
        # Fall back to the generic 500 template until a dedicated 413 page exists.
        return render_template("errors/500.html"), 413

    @app.route("/health")
    def health():
        try:
            db = get_db()
            db.execute(text("SELECT 1"))
            return jsonify({"status": "ok", "database": "connected"})
        except Exception:
            return jsonify({"status": "degraded", "database": "disconnected"}), 503

    @app.route("/")
    def landing():
        user = g.get("current_user")
        if user:
            role_dashboards = {
                "client_admin": "client.dashboard",
                "client_user": "client.dashboard",
                "caterer": "caterer.dashboard",
                "super_admin": "admin.dashboard",
            }
            endpoint = role_dashboards.get(user.role, "client.dashboard")
            return redirect(url_for(endpoint))
        db = get_db()
        caterer_count = db.scalar(
            select(func.count(Caterer.id)).where(Caterer.is_validated.is_(True))
        ) or 0
        company_count = db.scalar(select(func.count(Company.id))) or 0
        order_count = db.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.paid)
        ) or 0
        return render_template(
            "landing.html",
            caterer_count=caterer_count,
            company_count=company_count,
            order_count=order_count,
        )

    return app


if __name__ == "__main__":
    # Debug only on opt-in via env. The Werkzeug debugger executes arbitrary
    # code through its console — must never be on in production. Audit VULN-17
    # / Bandit B201. Production runs through gunicorn (entrypoint.sh) which
    # ignores this block entirely, so the practical risk is a `python app.py`
    # in dev with FLASK_DEBUG accidentally set in the environment.
    import os
    debug_flag = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    create_app().run(debug=debug_flag, port=8000)
