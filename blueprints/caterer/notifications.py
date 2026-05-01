"""Caterer-side notifications page. Mirrors blueprints/client/notifications.py
— same template, only the role gate + mark-all endpoint name differ."""

from flask import flash, g, redirect, render_template, url_for
from sqlalchemy import select, update

from blueprints.middleware import login_required, role_required
from database import get_db
from models import Notification
from services.notifications import notification_target_url


def register(bp):
    @bp.route("/notifications")
    @login_required
    @role_required("caterer")
    def notifications():
        user = g.current_user
        db = get_db()
        notes = db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc())
            .limit(100)
        ).all()
        unread_count = sum(1 for n in notes if not n.is_read)
        return render_template(
            "notifications/list.html",
            user=user,
            notes=notes,
            unread_count=unread_count,
            mark_all_endpoint="caterer.notifications_mark_all_read",
            read_one_endpoint="caterer.notifications_read_one",
        )

    @bp.route("/notifications/<uuid:notification_id>/read", methods=["POST"])
    @login_required
    @role_required("caterer")
    def notifications_read_one(notification_id):
        user = g.current_user
        db = get_db()
        note = db.get(Notification, notification_id)
        if note and note.user_id == user.id:
            note.is_read = True
            db.commit()
        return redirect(url_for("caterer.notifications"))

    @bp.route("/notifications/<uuid:notification_id>/visit", methods=["POST"])
    @login_required
    @role_required("caterer")
    def notifications_visit(notification_id):
        user = g.current_user
        db = get_db()
        note = db.get(Notification, notification_id)
        target = url_for("caterer.notifications")
        if note and note.user_id == user.id:
            resolved = notification_target_url(note, user.role)
            if resolved:
                target = resolved
            note.is_read = True
            db.commit()
        return redirect(target)

    @bp.route("/notifications/mark-all-read", methods=["POST"])
    @login_required
    @role_required("caterer")
    def notifications_mark_all_read():
        user = g.current_user
        db = get_db()
        db.execute(
            update(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
            .values(is_read=True)
        )
        db.commit()
        flash("Toutes les notifications sont marquées comme lues.", "info")
        return redirect(url_for("caterer.notifications"))
