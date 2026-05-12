import os
from datetime import timedelta

from flask import (
    Flask,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix
from whitenoise import WhiteNoise

import config
from config import settings
from database import ScopedSession, get_db
from extensions import csrf, limiter
from logging_config import configure_logging, install_request_id_hooks
from models import (
    Caterer,
    Company,
    MembershipStatus,
    Order,
    OrderStatus,
    PaymentStatus,
    QRCStatus,
    QuoteRequestStatus,
    QuoteStatus,
    User,
    UserRole,
)

# A non-active membership status should not authorize action. Only users
# approved by a client_admin (or users whose role does not use the
# membership flow) are loaded as the current user. Audit finding #4.
# Pending users (signup-against-existing-SIRET) and rejected users are not
# authenticated as far as the request handlers are concerned. The login
# endpoint also rejects them upfront so the session cookie is never issued.
# Defense in depth: even if a stale session sneaks through, /load_current_user
# wipes g.current_user before any view runs.
_BLOCKED_MEMBERSHIP_STATUSES = {MembershipStatus.pending, MembershipStatus.rejected}

configure_logging()


CSP = (
    "default-src 'self'; "
    # VULN-105: lucide + chart.js are now bundled in static/js/vendor/,
    # so we drop https://unpkg.com and https://cdn.jsdelivr.net from
    # script-src. Tightens the supply-chain surface to first-party only.
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    # `blob:` est requis pour afficher les previews de fichiers cote client
    # (URL.createObjectURL utilise par caterer-profile.js). Les blob URLs
    # sont generees par le navigateur lui-meme a partir de fichiers locaux,
    # donc elles n'ouvrent aucune surface reseau ni cross-origin.
    "img-src 'self' data: blob:; "
    # api-adresse.data.gouv.fr is the BAN (Base Adresse Nationale)
    # public endpoint — CORS-enabled, no key required — we call it
    # from the address autocomplete on /client/requests/new and /edit.
    "connect-src 'self' https://api-adresse.data.gouv.fr; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY

    # Whitenoise serves /static/* at the WSGI layer, before Flask routing —
    # avoids waking the full Flask stack (request middleware, blueprint
    # dispatch, login_required, notification injection, etc.) for every
    # CSS/JS/image. On Scalingo this is the only thing keeping static-asset
    # traffic off the gunicorn worker pool (no Caddy in front of the dyno).
    # On self-hosted (docker-compose.{staging,prod}.yml), Caddy intercepts
    # /static/* first via handle_path, so Whitenoise sits dormant there.
    #
    # max_age=3600 (not `immutable`) because CSS/JS filenames in this project
    # are NOT content-hashed; longer caching would strand stale assets after
    # a deploy. Whitenoise still emits ETag so revalidation is a cheap 304.
    # Uploads are not in static/ on Scalingo (they live on S3 with their own
    # immutable Cache-Control set in services/uploads.py:_save_s3).
    app.wsgi_app = WhiteNoise(
        app.wsgi_app,
        root=os.path.join(os.path.dirname(__file__), "static"),
        prefix="/static/",
        max_age=3600,
        autorefresh=os.getenv("FLASK_DEBUG") == "1",
    )

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
        # Dev-only template auto-reload. On Docker Desktop Windows the bind
        # mount drops mtime updates, so Jinja's default mtime-based cache
        # serves stale templates after every edit. Setting this to True
        # makes Jinja stat the file on every render — slower (~5%) but
        # makes the dev workflow predictable. Off in prod.
        TEMPLATES_AUTO_RELOAD=os.getenv("TEMPLATES_AUTO_RELOAD") == "1",
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
    from blueprints.uploads import uploads_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(caterer_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(uploads_bp)

    # Per-blueprint rate limits (on top of the global default).
    # Write-heavy blueprints get tighter caps; API gets its own ceiling.
    limiter.limit("30 per minute", per_method=True, methods=["POST"])(client_bp)
    limiter.limit("30 per minute", per_method=True, methods=["POST"])(caterer_bp)
    limiter.limit("20 per minute", per_method=True, methods=["POST"])(admin_bp)

    # Dev-only account switcher. Tied to the same env flag that seeds the
    # demo data so production (where the flag is empty) never registers
    # the route. See blueprints/devtools.py for the safety rationale.
    # `os` is imported at module level above.
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

    @app.context_processor
    def _inject_notifications():
        # Surface the recent UNREAD notifications + the role-aware URL
        # resolver to base.html so the topbar bell can show a dropdown
        # without an extra round-trip per page. Cap at 10 — once a
        # notification is consulted (marked read), it leaves the
        # dropdown but stays accessible via the dedicated /notifications
        # history page. `notifications_unread_total` is the true count
        # (not capped) so the modal header doesn't read "10 non lues"
        # when there are actually 25.
        from models import Notification as _Notification
        from services.notifications import (
            get_unread_count,
            notification_target_url,
        )

        if not g.get("current_user"):
            return {
                "notifications_recent": [],
                "notifications_unread_total": 0,
                "notification_target_url": notification_target_url,
            }
        db = get_db()
        recent = db.scalars(
            select(_Notification)
            .where(
                _Notification.user_id == g.current_user.id,
                _Notification.is_read.is_(False),
            )
            .order_by(_Notification.created_at.desc())
            .limit(10)
        ).all()
        # Skip the extra COUNT when we're below the cap — the list
        # length is exact in that case.
        unread_total = (
            len(recent) if len(recent) < 10 else get_unread_count(db, g.current_user.id)
        )
        return {
            "notifications_recent": recent,
            "notifications_unread_total": unread_total,
            "notification_target_url": notification_target_url,
        }

    # CLI for ops tasks: `flask admin create / reset-password / list / disable`.
    # Avoids relying on ADMIN_INITIAL_PASSWORD env var for day-to-day admin
    # lifecycle (P3.2).
    # `uploads migrate-to-s3` is the one-shot migration script that lifts
    # legacy /static/uploads/* references onto the S3 bucket.
    from cli import admin_cli, uploads_cli

    app.cli.add_command(admin_cli)
    app.cli.add_command(uploads_cli)

    @app.before_request
    def load_current_user():
        g.current_user = None
        if request.endpoint and (
            request.endpoint in ("static", "health") or (request.blueprint == "auth")
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
            if user and not user.is_active:
                session.clear()
                user = None
            if user:
                # Session invalidation on password reset: the snapshot
                # stored at login must still match the live column.
                # Mismatch = the user reset their password from another
                # device/IP, so this session is stale.
                #
                # We pull the column with a fresh scalar query rather
                # than reading user.password_changed_at directly: a
                # parallel commit (other tab, other process) updates
                # the row, but a session whose identity map already
                # holds the User instance may serve a stale attribute.
                # The dedicated column query bypasses the identity map.
                stamped = session.get("pwd_changed_at")
                live_at = db.scalar(
                    select(User.password_changed_at).where(User.id == user_id)
                )
                live = live_at.isoformat() if live_at else None
                if stamped != live:
                    session.clear()
                    user = None
            g.current_user = user

    @app.before_request
    def mark_notifications_read_on_entity_view():
        """Clear bell-dropdown notifications whose related entity the
        user has just landed on — irrespective of how they got there
        (dashboard tile, list page, direct link, dropdown click).

        Runs after `load_current_user` (registration order) so
        `g.current_user` is set. GET-only: POSTs to the same URL are
        actions, not "viewing".

        Commits on its own because the typical detail handler is a
        read and doesn't commit; without an explicit commit here the
        notification update would be discarded at request teardown.
        Failures are swallowed so a DB hiccup on marking-read can't
        500 the user's main request — they'll just see the notif
        again on the next page load.
        """
        if request.method != "GET":
            return
        if not g.get("current_user"):
            return
        endpoint = request.endpoint
        if not endpoint:
            return

        from services.notifications import (
            mark_read_by_type,
            mark_read_for_entities,
            mark_read_for_entity,
        )

        args = request.view_args or {}
        db = get_db()
        user = g.current_user
        user_id = user.id
        touched = False

        try:
            if endpoint in (
                "client.request_detail",
                "caterer.request_detail",
                "admin.qualification_detail",
            ):
                rid = args.get("request_id") or args.get("qr_id")
                if rid:
                    touched |= bool(
                        mark_read_for_entity(db, user_id, "quote_request", rid)
                    )
                    # Quote-related notifs bounce to the parent request URL
                    # (see services.notifications.notification_target_url),
                    # so visiting the request also clears those.
                    from models import Quote

                    quote_ids = list(
                        db.scalars(
                            select(Quote.id).where(Quote.quote_request_id == rid)
                        )
                    )
                    if quote_ids:
                        touched |= bool(
                            mark_read_for_entities(db, user_id, "quote", quote_ids)
                        )
            elif endpoint in (
                "client.order_detail",
                "caterer.order_detail",
                "admin.order_detail",
            ):
                oid = args.get("order_id")
                if oid:
                    touched |= bool(mark_read_for_entity(db, user_id, "order", oid))
            elif endpoint == "admin.caterer_detail":
                cid = args.get("caterer_id")
                if cid:
                    touched |= bool(mark_read_for_entity(db, user_id, "caterer", cid))
            elif endpoint in (
                "client.message_thread",
                "caterer.message_thread",
                "admin.message_thread",
            ):
                tid = args.get("thread_id")
                if tid:
                    from models import Message

                    msg_ids = list(
                        db.scalars(select(Message.id).where(Message.thread_id == tid))
                    )
                    if msg_ids:
                        touched |= bool(
                            mark_read_for_entities(db, user_id, "message", msg_ids)
                        )
            elif endpoint == "client.dashboard":
                # `company`-type notifs (membership approval) resolve to
                # the dashboard. Scope by the user's own company_id so
                # the sweep stays narrow.
                if user.company_id:
                    touched |= bool(
                        mark_read_for_entity(db, user_id, "company", user.company_id)
                    )
            elif endpoint == "client.team":
                # Pending-membership notifs (related_entity_type="user")
                # all surface on the team page, regardless of which user
                # is pending. URL has no entity_id, so sweep by type.
                # Only emitted to client_admins — gate explicitly to keep
                # the sweep scoped to roles that actually receive them.
                if user.role == UserRole.client_admin:
                    touched |= bool(mark_read_by_type(db, user_id, "user"))

            if touched:
                db.commit()
        except SQLAlchemyError:
            db.rollback()

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
        except SQLAlchemyError:
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

    @app.errorhandler(429)
    def _rate_limited(_e):
        # Flask-Limiter's default 429 page is bare text on a white background.
        # Render the styled template so the user gets the same shell as the
        # rest of the site and a clear "wait a bit" message.
        if request.path.startswith("/api/"):
            return jsonify(
                {"error": "Trop de tentatives. Patientez quelques minutes."}
            ), 429
        return render_template("errors/429.html"), 429

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
        except SQLAlchemyError:
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
        caterer_count = (
            db.scalar(
                select(func.count(Caterer.id)).where(Caterer.is_validated.is_(True))
            )
            or 0
        )
        company_count = db.scalar(select(func.count(Company.id))) or 0
        order_count = (
            db.scalar(
                select(func.count(Order.id)).where(Order.status == OrderStatus.paid)
            )
            or 0
        )
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
    debug_flag = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    create_app().run(debug=debug_flag, port=8000)
