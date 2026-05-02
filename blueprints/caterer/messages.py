from flask import abort, g, render_template

from blueprints.middleware import login_required, role_required
from database import get_db
from models import UserRole
from services.messagerie import active_thread_context, threads_for_viewer


def _build_ctx(*, viewer, threads, active_thread_id, active):
    return {
        "threads": threads,
        "active_thread_id": active_thread_id,
        "active": active,
        "list_endpoint": "caterer.messages",
        "thread_endpoint": "caterer.message_thread",
        "show_role_badges": viewer.role == UserRole.super_admin,
        "read_only": False,
        "current_user_id": str(viewer.id),
    }


def register(bp):
    @bp.route("/messages")
    @login_required
    @role_required("caterer")
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
    @role_required("caterer")
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
