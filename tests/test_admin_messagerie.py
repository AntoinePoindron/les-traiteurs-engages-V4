"""Tests for the super_admin messagerie — participant model.

Before this change the super_admin was a platform-wide read-only
observer: `threads_for_admin` listed every thread, `read_only=True`
hid the composer, and `qualification_message` sent a Notification
instead of opening a real conversation.

It now participates like any other role — its own conversations, a
working composer, and the ability to open a conversation with any
active user. Each test below would fail against the old observer code.

Lazy imports inside the test bodies follow the project convention
(see tests/test_notifications.py): `database` must not bind its engine
before conftest switches DATABASE_URL to `traiteurs_test`.
"""

import uuid


def _user_id(s, email):
    from sqlalchemy import select

    from models import User

    return s.scalar(select(User.id).where(User.email == email))


def _seed_message(s, *, sender_id, recipient_id, body="ping", thread_id=None):
    """Insert one Message and return its thread_id."""
    from models import Message

    tid = thread_id or uuid.uuid4()
    s.add(
        Message(
            thread_id=tid,
            sender_id=sender_id,
            recipient_id=recipient_id,
            body=body,
        )
    )
    s.flush()
    return tid


def _wipe_messages():
    """Drop every Message row so threads don't leak between tests."""
    from database import session_factory
    from models import Message

    s = session_factory()
    try:
        s.execute(Message.__table__.delete())
        s.commit()
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Composer — the admin messagerie is no longer read-only
# ---------------------------------------------------------------------------


def test_admin_thread_view_renders_a_working_composer(client, login):
    """Opening a thread the admin takes part in must render the send
    form, not the old read-only 'envoi désactivé' notice."""
    from database import session_factory

    s = session_factory()
    try:
        tid = _seed_message(
            s,
            sender_id=_user_id(s, "admin@test.local"),
            recipient_id=_user_id(s, "alice@test.local"),
        )
        s.commit()
    finally:
        s.close()

    try:
        login("admin@test.local")
        r = client.get(f"/admin/messages/{tid}", follow_redirects=False)
        assert r.status_code == 200
        html = r.data.decode("utf-8", errors="replace")
        assert 'id="message-form"' in html, (
            "the admin thread view must render the composer form"
        )
        assert "l'envoi de messages est désactivé" not in html, (
            "the old read-only notice must be gone"
        )
    finally:
        _wipe_messages()


# ---------------------------------------------------------------------------
# Participation gate — the admin only sees its own conversations
# ---------------------------------------------------------------------------


def test_admin_cannot_open_a_thread_it_does_not_participate_in(client, login):
    """A thread strictly between a client and a caterer is invisible to
    the admin — it participates now, it no longer observes the whole
    platform. Old behaviour: super_admin got a 200 on any thread."""
    from database import session_factory

    s = session_factory()
    try:
        tid = _seed_message(
            s,
            sender_id=_user_id(s, "alice@test.local"),
            recipient_id=_user_id(s, "cook@test.local"),
        )
        s.commit()
    finally:
        s.close()

    try:
        login("admin@test.local")
        r = client.get(f"/admin/messages/{tid}", follow_redirects=False)
        assert r.status_code == 404, (
            "admin must not reach a thread it isn't a participant of"
        )
    finally:
        _wipe_messages()


def test_admin_inbox_lists_only_its_own_threads(client, login):
    """The inbox lists the admin's own threads only. A client↔caterer
    thread must not surface — old `threads_for_admin` listed every
    thread on the platform."""
    from database import session_factory

    s = session_factory()
    try:
        own_tid = _seed_message(
            s,
            sender_id=_user_id(s, "admin@test.local"),
            recipient_id=_user_id(s, "alice@test.local"),
        )
        foreign_tid = _seed_message(
            s,
            sender_id=_user_id(s, "alice@test.local"),
            recipient_id=_user_id(s, "cook@test.local"),
        )
        s.commit()
    finally:
        s.close()

    try:
        login("admin@test.local")
        r = client.get("/admin/messages", follow_redirects=False)
        assert r.status_code == 200
        html = r.data.decode("utf-8", errors="replace")
        assert str(own_tid) in html, "admin's own thread must be listed"
        assert str(foreign_tid) not in html, (
            "a client↔caterer thread must not leak into the admin inbox"
        )
    finally:
        _wipe_messages()


# ---------------------------------------------------------------------------
# Sending — admin can open a conversation with any active user
# ---------------------------------------------------------------------------


def test_admin_can_message_any_active_user(client, login):
    """The admin can start a conversation with any active account,
    regardless of a shared order / quote-request context."""
    from sqlalchemy import select

    from database import session_factory
    from models import Message

    s = session_factory()
    try:
        cook_id = _user_id(s, "cook@test.local")
        admin_id = _user_id(s, "admin@test.local")
    finally:
        s.close()

    try:
        login("admin@test.local")
        r = client.post(
            "/api/messages",
            json={"recipient_id": str(cook_id), "body": "Bonjour"},
        )
        assert r.status_code == 201, r.data
        thread_id = r.get_json()["thread_id"]

        s = session_factory()
        try:
            msg = s.scalar(
                select(Message).where(Message.thread_id == uuid.UUID(thread_id))
            )
            assert msg is not None
            assert msg.sender_id == admin_id
            assert msg.recipient_id == cook_id
            assert msg.body == "Bonjour"
        finally:
            s.close()
    finally:
        _wipe_messages()


def test_admin_message_to_unknown_recipient_is_rejected(client, login):
    """An admin send to a recipient_id that resolves to no user must
    404 — the old code skipped the gate entirely for admins and would
    have persisted a message onto a ghost row."""
    from sqlalchemy import func, select

    from database import session_factory
    from models import Message

    login("admin@test.local")
    r = client.post(
        "/api/messages",
        json={"recipient_id": str(uuid.uuid4()), "body": "vers le vide"},
    )
    assert r.status_code == 404, r.data

    s = session_factory()
    try:
        assert s.scalar(select(func.count(Message.id))) == 0, (
            "no message row may be created for an unknown recipient"
        )
    finally:
        s.close()


def test_admin_message_to_inactive_recipient_is_rejected(client, login):
    """A deactivated account is not a valid conversation target."""
    from sqlalchemy import select

    from database import session_factory
    from models import User, UserRole

    s = session_factory()
    try:
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))
        ghost = User(
            email=f"inactive-{uuid.uuid4().hex[:8]}@test.local",
            password_hash="x",
            first_name="In",
            last_name="Active",
            role=UserRole.client_user,
            company_id=alice.company_id,
            is_active=False,
        )
        s.add(ghost)
        s.commit()
        ghost_id = ghost.id
    finally:
        s.close()

    try:
        login("admin@test.local")
        r = client.post(
            "/api/messages",
            json={"recipient_id": str(ghost_id), "body": "coucou"},
        )
        assert r.status_code == 404, r.data
    finally:
        _wipe_messages()
        s = session_factory()
        try:
            s.execute(User.__table__.delete().where(User.id == ghost_id))
            s.commit()
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Entry point — the quote-request detail opens a real conversation
# ---------------------------------------------------------------------------


def _seed_qr_for_alice(s):
    """Minimal pending_review QuoteRequest owned by alice@test.local."""
    import datetime as _dt

    from sqlalchemy import select

    from models import Company, QuoteRequest, QuoteRequestStatus, User

    acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
    alice = s.scalar(select(User).where(User.email == "alice@test.local"))
    qr = QuoteRequest(
        company_id=acme.id,
        user_id=alice.id,
        guest_count=10,
        status=QuoteRequestStatus.pending_review,
        event_address="1 rue Test",
        event_city="Paris",
        event_zip_code="75001",
        event_date=_dt.date.today() + _dt.timedelta(days=21),
    )
    s.add(qr)
    s.flush()
    return qr.id


def test_qr_detail_uses_the_conversation_modal(client, login):
    """The quote-request detail must wire the real send-message modal
    (a Message thread), not the old notification-only dialog."""
    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        qr_id = _seed_qr_for_alice(s)
        s.commit()
    finally:
        s.close()

    try:
        login("admin@test.local")
        r = client.get(f"/admin/qualification/{qr_id}", follow_redirects=False)
        assert r.status_code == 200
        html = r.data.decode("utf-8", errors="replace")
        assert "admin-client-message-modal" in html, (
            "the QR detail must render the conversation send-message modal"
        )
        assert f"/admin/qualification/{qr_id}/message" not in html, (
            "the old qualification_message form action must be gone"
        )
    finally:
        s = session_factory()
        try:
            s.execute(QuoteRequest.__table__.delete().where(QuoteRequest.id == qr_id))
            s.commit()
        finally:
            s.close()


def test_qualification_message_route_is_removed(client, login):
    """The old notification-only endpoint no longer exists."""
    login("admin@test.local")
    r = client.post(
        f"/admin/qualification/{uuid.uuid4()}/message",
        data={"body": "x"},
    )
    assert r.status_code == 404, (
        "the qualification_message route must be gone (replaced by conversations)"
    )
