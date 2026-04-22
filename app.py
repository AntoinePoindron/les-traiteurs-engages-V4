from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select, text

import config
from database import ScopedSession, get_session
from models import Caterer, Company, Order, OrderStatus, User


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY

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

    @app.cli.command("init-db")
    def init_db_command():
        from database import init_db

        init_db()
        print("Database initialized.")

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
            with get_session() as db:
                g.current_user = db.execute(
                    select(User).where(User.id == user_id)
                ).scalar_one_or_none()

    @app.teardown_appcontext
    def remove_session(exc=None):
        ScopedSession.remove()

    @app.route("/health")
    def health():
        try:
            with get_session() as db:
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
        with get_session() as db:
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
    create_app().run(debug=True, port=8000)
