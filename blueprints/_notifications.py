"""Shared notifications routes for client/caterer/admin blueprints.

Endpoint names are derived from the blueprint name (e.g. `client.notifications`),
so call sites only differ by which roles are authorized.
"""

from flask import flash, g, redirect, render_template, url_for
from sqlalchemy import select, update

from blueprints.middleware import login_required, role_required
from database import get_db
from models import Notification
from services.notifications import notification_target_url


def register(bp, *, roles):
    prefix = bp.name
    list_endpoint = f"{prefix}.notifications"

    @bp.route("/notifications")
    @login_required
    @role_required(*roles)
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
            mark_all_endpoint=f"{prefix}.notifications_mark_all_read",
            read_one_endpoint=f"{prefix}.notifications_read_one",
        )

    @bp.route("/notifications/<uuid:notification_id>/read", methods=["POST"])
    @login_required
    @role_required(*roles)
    def notifications_read_one(notification_id):
        user = g.current_user
        db = get_db()
        note = db.get(Notification, notification_id)
        if note and note.user_id == user.id:
            note.is_read = True
            db.commit()
        return redirect(url_for(list_endpoint))

    @bp.route("/notifications/<uuid:notification_id>/visit", methods=["POST"])
    @login_required
    @role_required(*roles)
    def notifications_visit(notification_id):
        user = g.current_user
        db = get_db()
        note = db.get(Notification, notification_id)
        target = url_for(list_endpoint)
        if note and note.user_id == user.id:
            resolved = notification_target_url(note, user.role)
            if resolved:
                target = resolved
            note.is_read = True
            db.commit()
        return redirect(target)

    @bp.route("/notifications/mark-all-read", methods=["POST"])
    @login_required
    @role_required(*roles)
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
        return redirect(url_for(list_endpoint))
