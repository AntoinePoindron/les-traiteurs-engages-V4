"""Regression tests for /client/messages/with/<user_id> and
/caterer/messages/with/<user_id> — the "Envoyer un message" entry
points used by buttons across order/request detail pages.

Behavior:
  * if a thread already exists between the viewer and the target user,
    302 to that thread URL;
  * otherwise, render the messagerie page in compose-mode (right pane
    has the recipient pre-filled, no thread_id, the form posts to
    /api/messages which auto-creates the thread on first send).

Convention d'imports lazy : `database` est importé *à l'intérieur* des
fonctions pour que conftest puisse switcher sur `traiteurs_test` avant
le binding de l'engine.
"""

import uuid


def test_message_with_creates_compose_pane_when_no_thread(client, login):
    """A client clicking 'Envoyer un message' on a caterer they've
    never messaged before lands on the messagerie page in compose
    mode — the recipient is pre-filled, the conversation pane is
    empty, and the form is ready to send the first message."""
    from sqlalchemy import select

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        cook = s.scalar(select(User).where(User.email == "cook@test.local"))
        cook_id = str(cook.id)
    finally:
        s.close()

    login("alice@test.local")
    r = client.get(f"/client/messages/with/{cook_id}", follow_redirects=False)
    assert r.status_code == 200, "compose-mode page must render with 200"
    body = r.data.decode("utf-8", errors="replace")
    # The hidden recipient_id input drives /api/messages on first send.
    assert f'value="{cook_id}"' in body, (
        "recipient_id must be pre-filled with the target user"
    )
    # The send form must be present (not the read-only admin variant).
    assert 'id="message-form"' in body
    # No thread_id yet — messages-container's data attribute is empty.
    assert 'data-thread-id=""' in body, (
        "compose mode must leave data-thread-id empty so JS skips the load"
    )


def test_message_with_redirects_when_thread_exists(client, login):
    """When a thread already exists with the target user, the entry
    point 302s to that thread URL instead of showing compose mode."""
    from sqlalchemy import select

    from database import session_factory
    from models import Message, User

    s = session_factory()
    try:
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))
        cook = s.scalar(select(User).where(User.email == "cook@test.local"))
        thread_id = uuid.uuid4()
        # Two messages so the thread definitely exists from both sides.
        s.add(
            Message(
                thread_id=thread_id,
                sender_id=alice.id,
                recipient_id=cook.id,
                body="hi",
            )
        )
        s.commit()
        cook_id = str(cook.id)
        thread_id_str = str(thread_id)
    finally:
        s.close()

    try:
        login("alice@test.local")
        r = client.get(f"/client/messages/with/{cook_id}", follow_redirects=False)
        assert r.status_code == 302, "must 302 to the existing thread"
        assert thread_id_str in r.headers["Location"], (
            f"redirect target must be the existing thread, got {r.headers['Location']!r}"
        )
    finally:
        s = session_factory()
        try:
            s.execute(
                Message.__table__.delete().where(Message.thread_id == thread_id)
            )
            s.commit()
        finally:
            s.close()


def test_message_with_works_from_caterer_side(client, login):
    """Symmetric: a caterer clicking 'Envoyer un message' on a client
    they've never messaged before lands in compose mode under the
    caterer blueprint's URL."""
    from sqlalchemy import select

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))
        alice_id = str(alice.id)
    finally:
        s.close()

    login("cook@test.local")
    r = client.get(f"/caterer/messages/with/{alice_id}", follow_redirects=False)
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert f'value="{alice_id}"' in body


def test_message_with_self_404s(client, login):
    """Messaging yourself isn't a real conversation — block it so the
    button can't be misused via URL fiddling."""
    from sqlalchemy import select

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))
        alice_id = str(alice.id)
    finally:
        s.close()

    login("alice@test.local")
    r = client.get(f"/client/messages/with/{alice_id}", follow_redirects=False)
    assert r.status_code == 404


def test_message_with_unknown_user_404s(client, login):
    """Pointing at a user_id that doesn't resolve must 404, not 500."""
    login("alice@test.local")
    fake_id = uuid.uuid4()
    r = client.get(f"/client/messages/with/{fake_id}", follow_redirects=False)
    assert r.status_code == 404


def test_message_with_forwards_order_context_to_form(client, login):
    """When the entry point is hit with `?order_id=...`, the compose
    form must carry the order_id as a hidden input. Without it, the
    first send hits the VULN-04 gate in /api/messages and bounces
    with "le message doit etre lie a une commande..."."""
    from sqlalchemy import select

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        cook = s.scalar(select(User).where(User.email == "cook@test.local"))
        cook_id = str(cook.id)
    finally:
        s.close()

    fake_order_id = uuid.uuid4()  # Real lookup happens server-side at POST time.
    login("alice@test.local")
    r = client.get(
        f"/client/messages/with/{cook_id}?order_id={fake_order_id}",
        follow_redirects=False,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert f'name="order_id" value="{fake_order_id}"' in body, (
        "compose form must carry the order_id hidden input"
    )


def test_message_with_forwards_quote_request_context_to_form(client, login):
    """Symmetric: `?quote_request_id=...` propagates to the form."""
    from sqlalchemy import select

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        cook = s.scalar(select(User).where(User.email == "cook@test.local"))
        cook_id = str(cook.id)
    finally:
        s.close()

    fake_qr_id = uuid.uuid4()
    login("alice@test.local")
    r = client.get(
        f"/client/messages/with/{cook_id}?quote_request_id={fake_qr_id}",
        follow_redirects=False,
    )
    assert r.status_code == 200
    body = r.data.decode("utf-8", errors="replace")
    assert f'name="quote_request_id" value="{fake_qr_id}"' in body
