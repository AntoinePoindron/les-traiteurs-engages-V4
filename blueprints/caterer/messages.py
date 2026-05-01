from flask import abort, g, render_template
from sqlalchemy import func, or_, select

from blueprints.middleware import login_required, role_required
from database import get_db
from models import Message, User


def _get_caterer_threads(db, user_id):
    all_messages = db.scalars(
        select(Message)
        .where(or_(Message.sender_id == user_id, Message.recipient_id == user_id))
        .order_by(Message.created_at.desc())
    ).all()
    threads = {}
    for msg in all_messages:
        tid = str(msg.thread_id)
        if tid not in threads:
            other_id = msg.recipient_id if msg.sender_id == user_id else msg.sender_id
            other_user = db.get(User, other_id)
            unread = db.scalar(
                select(func.count(Message.id)).where(
                    Message.thread_id == msg.thread_id,
                    Message.recipient_id == user_id,
                    Message.is_read.is_(False),
                )
            )
            threads[tid] = {
                "thread_id": tid,
                "other_name": f"{other_user.first_name} {other_user.last_name}"
                if other_user
                else "Inconnu",
                "last_message": msg.body[:80],
                "last_at": msg.created_at,
                "unread": unread,
            }
    return list(threads.values())


def register(bp):
    @bp.route("/messages")
    @login_required
    @role_required("caterer")
    def messages():
        user = g.current_user
        db = get_db()
        threads = _get_caterer_threads(db, user.id)
        return render_template("caterer/messages/list.html", user=user, threads=threads)

    @bp.route("/messages/<uuid:thread_id>")
    @login_required
    @role_required("caterer")
    def message_thread(thread_id):
        user = g.current_user
        db = get_db()
        first_msg = db.scalar(
            select(Message).where(
                Message.thread_id == thread_id,
                or_(Message.sender_id == user.id, Message.recipient_id == user.id),
            )
        )
        if not first_msg:
            abort(404)
        other_id = (
            first_msg.recipient_id
            if first_msg.sender_id == user.id
            else first_msg.sender_id
        )
        other_user = db.get(User, other_id)
        return render_template(
            "caterer/messages/thread.html",
            user=user,
            thread_id=thread_id,
            other_user=other_user,
        )
