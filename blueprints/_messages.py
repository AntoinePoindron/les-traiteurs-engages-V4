"""Shared messagerie routes for client/caterer blueprints.

Endpoint names are derived from the blueprint name (e.g. `client.messages`),
so call sites only differ by which roles are authorized. Admin's messages
view is paginated and lives in blueprints/admin.py separately.
"""

from flask import abort, g, render_template

from blueprints.middleware import (
    login_required,
    role_required,
    validated_caterer_required,
)
from database import get_db
from models import UserRole
from services.messagerie import active_thread_context, threads_for_viewer


def register(bp, *, roles):
    prefix = bp.name

    def _build_ctx(*, viewer, threads, active_thread_id, active):
        return {
            "threads": threads,
            "active_thread_id": active_thread_id,
            "active": active,
            "list_endpoint": f"{prefix}.messages",
            "thread_endpoint": f"{prefix}.message_thread",
            "show_role_badges": viewer.role == UserRole.super_admin,
            "read_only": False,
            "current_user_id": str(viewer.id),
        }

    @bp.route("/messages")
    @login_required
    @role_required(*roles)
    @validated_caterer_required
    def messages():
        user = g.current_user
        db = get_db()
        threads = threads_for_viewer(db, user)
        return render_template(
            "messagerie/page.html",
            user=user,
            messagerie_ctx=_build_ctx(
                viewer=user,
                threads=threads,
                active_thread_id=None,
                active=None,
            ),
        )

    @bp.route("/messages/<uuid:thread_id>")
    @login_required
    @role_required(*roles)
    @validated_caterer_required
    def message_thread(thread_id):
        user = g.current_user
        db = get_db()
        active = active_thread_context(db, thread_id=thread_id, viewer=user)
        if active is None:
            abort(404)
        threads = threads_for_viewer(db, user)
        return render_template(
            "messagerie/page.html",
            user=user,
            messagerie_ctx=_build_ctx(
                viewer=user,
                threads=threads,
                active_thread_id=str(thread_id),
                active=active,
            ),
        )
