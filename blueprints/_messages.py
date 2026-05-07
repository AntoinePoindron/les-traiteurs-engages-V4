"""Shared messagerie routes for client/caterer blueprints.

Endpoint names are derived from the blueprint name (e.g. `client.messages`),
so call sites only differ by which roles are authorized. Admin's messages
view is paginated and lives in blueprints/admin.py separately.
"""

from flask import abort, g, redirect, render_template, request, url_for

from blueprints.middleware import login_required, role_required
from database import get_db
from models import UserRole
from services.messagerie import (
    active_thread_context,
    compose_thread_context,
    find_thread_with,
    threads_for_viewer,
)


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

    @bp.route("/messages/with/<uuid:user_id>")
    @login_required
    @role_required(*roles)
    def message_with(user_id):
        """Entry point for "Envoyer un message" buttons across the app.

        - If a thread already exists between the viewer and `user_id`,
          302 to that thread URL.
        - Otherwise, render the messagerie page in compose-mode: right
          pane shows the recipient + an empty conversation + the
          message form pre-filled with the recipient. JS adopts the
          thread_id returned by /api/messages after the first send.

        Optional `?order_id=` / `?quote_request_id=` query params are
        forwarded into the form as hidden inputs so the first message
        satisfies the VULN-04 business-relation gate in /api/messages
        (without an inheritable thread history, the API requires an
        explicit context). Buttons that live on order/request detail
        pages set them; buttons that don't have a natural context
        (e.g. from a profile page) omit them, and the API will need
        thread history to clear the gate.
        """
        user = g.current_user
        db = get_db()
        existing_thread_id = find_thread_with(
            db, viewer=user, other_user_id=user_id
        )
        if existing_thread_id:
            return redirect(
                url_for(f"{prefix}.message_thread", thread_id=existing_thread_id)
            )
        compose = compose_thread_context(
            db,
            viewer=user,
            other_user_id=user_id,
            order_id=request.args.get("order_id"),
            quote_request_id=request.args.get("quote_request_id"),
        )
        if compose is None:
            abort(404)
        threads = threads_for_viewer(db, user)
        return render_template(
            "messagerie/page.html",
            user=user,
            messagerie_ctx=_build_ctx(
                viewer=user,
                threads=threads,
                active_thread_id=None,
                active=compose,
            ),
        )
