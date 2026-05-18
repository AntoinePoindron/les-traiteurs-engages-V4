"""Red/green tests for the wizard double-submit guard.

Original bug: pressing Back after submitting the wizard restored the
cached form, the user re-clicked Submit, and a duplicate QuoteRequest
was persisted. The fix wires three layers of defence; this file
exercises the *server* one — a stable, browser-independent assertion
that the same idempotency token can never persist twice.

Test isolation strategy: the `traiteurs_test` DB is rebuilt once per
pytest session, not per test, so we cannot assume an empty
`quote_requests` table. We assert on **deltas** (rows created by THIS
test) and clean up by id (rows we know we created), never by
truncating the table — other tests in the suite hold quotes / QRCs
that FK-reference QuoteRequest rows.
"""

import re
import uuid


_REDIRECT_QR_ID = re.compile(r"/client/requests/([0-9a-f-]{36})")


def _qr_id_from_redirect(response) -> uuid.UUID | None:
    """Extract the new QR's UUID from a 302 Location pointing at
    `/client/requests/<id>`. Returns None if the redirect went
    elsewhere (validation failure, etc.) so callers can fail fast."""
    location = response.headers.get("Location", "")
    m = _REDIRECT_QR_ID.search(location)
    return uuid.UUID(m.group(1)) if m else None


def _delete_quote_requests(ids):
    """Drop ONLY the QuoteRequests this test created, by id, in a
    single statement. Tests we touch don't seed dependent rows
    (quotes/QRCs are created by accept/qualify flows, not by `POST
    /client/requests/new`), so a direct DELETE is safe — unlike a
    table-wide truncate, which would crash on FK refs from rows other
    tests own."""
    if not ids:
        return
    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        s.execute(QuoteRequest.__table__.delete().where(QuoteRequest.id.in_(list(ids))))
        s.commit()
    finally:
        s.close()


def _count_quote_requests() -> int:
    """Baseline / final count for delta-based assertions."""
    from sqlalchemy import func, select

    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        return s.scalar(select(func.count(QuoteRequest.id))) or 0
    finally:
        s.close()


def _minimal_wizard_payload(form_token: str | None) -> dict:
    """Smallest POST body that lets the wizard form pass validation.

    `QuoteRequestForm` declares every field Optional, so an essentially
    empty payload validates cleanly — exactly the surface we need to
    exercise the idempotency path without dragging the entire wizard's
    business rules into this suite.
    """
    payload: dict = {}
    if form_token is not None:
        payload["form_token"] = form_token
    return payload


def test_same_form_token_replayed_creates_only_one_quote_request(client, login):
    """Two POSTs carrying the same `form_token` must collapse onto a
    single row — the second response redirects to the existing detail
    page with an info flash."""
    login("alice@test.local")
    token = str(uuid.uuid4())
    baseline = _count_quote_requests()
    created_ids: set[uuid.UUID] = set()

    try:
        first = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(token),
            follow_redirects=False,
        )
        assert first.status_code == 302, (
            f"first wizard submission must redirect to the new detail; got "
            f"{first.status_code}"
        )
        first_id = _qr_id_from_redirect(first)
        assert first_id is not None, (
            f"first redirect must point at /client/requests/<uuid>; "
            f"got Location={first.headers.get('Location')!r}"
        )
        created_ids.add(first_id)
        assert _count_quote_requests() == baseline + 1, (
            "first submit should have created exactly one new QuoteRequest"
        )

        second = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(token),
            follow_redirects=False,
        )
        assert second.status_code == 302, (
            f"replay must redirect to the existing detail; got {second.status_code}"
        )
        second_id = _qr_id_from_redirect(second)
        assert second_id == first_id, (
            f"replay should point at the same QuoteRequest; "
            f"got {second_id} vs first {first_id}"
        )
        assert _count_quote_requests() == baseline + 1, (
            "a replayed form_token must NOT create a second QuoteRequest"
        )
    finally:
        _delete_quote_requests(created_ids)


def test_post_without_form_token_creates_a_quote_request(client, login):
    """Backwards-compat: a POST that omits the token (legacy form
    cached in a long-lived tab, or an older client) still goes through.
    The idempotency guard is opt-in via the hidden field."""
    login("alice@test.local")
    baseline = _count_quote_requests()
    created_ids: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(None),
            follow_redirects=False,
        )
        assert r.status_code == 302, (
            f"token-less submit must still create a request; got {r.status_code}"
        )
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None
        created_ids.add(new_id)
        assert _count_quote_requests() == baseline + 1
    finally:
        _delete_quote_requests(created_ids)


def test_malformed_form_token_falls_back_to_legacy_path(client, login):
    """A malformed token (anything that fails `uuid.UUID(...)`) is
    treated as no token at all. We explicitly accept this so a tampered
    payload can't 500 the wizard — the CSRF token is the real anti-replay
    guard for malicious flows."""
    login("alice@test.local")
    baseline = _count_quote_requests()
    created_ids: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload("not-a-uuid"),
            follow_redirects=False,
        )
        assert r.status_code == 302, (
            f"malformed token must fall back, not 500; got {r.status_code}"
        )
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None
        created_ids.add(new_id)
        assert _count_quote_requests() == baseline + 1
    finally:
        _delete_quote_requests(created_ids)


def test_two_distinct_tokens_create_two_quote_requests(client, login):
    """Sanity check the guard isn't too aggressive: two GENUINE new
    submissions (each with its own token, as a fresh GET would issue)
    must each produce their own row. This is the "double tab" / "user
    started a new wizard" scenario the PR explicitly preserves."""
    login("alice@test.local")
    baseline = _count_quote_requests()
    created_ids: set[uuid.UUID] = set()
    try:
        r1 = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(str(uuid.uuid4())),
            follow_redirects=False,
        )
        r2 = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(str(uuid.uuid4())),
            follow_redirects=False,
        )
        assert r1.status_code == 302 and r2.status_code == 302
        id1 = _qr_id_from_redirect(r1)
        id2 = _qr_id_from_redirect(r2)
        assert id1 is not None and id2 is not None
        assert id1 != id2, "distinct tokens must materialise as distinct rows"
        created_ids.update({id1, id2})
        assert _count_quote_requests() == baseline + 2, (
            "two distinct tokens must produce two new QuoteRequest rows"
        )
    finally:
        _delete_quote_requests(created_ids)


def test_wizard_get_emits_no_store_header(client, login):
    """The GET that issues the form must carry Cache-Control: no-store
    so the browser evicts the rendered HTML from bfcache — the layer
    that turns the back button into a re-submission risk in the first
    place."""
    login("alice@test.local")
    r = client.get("/client/requests/new")
    assert r.status_code == 200, r.data
    assert "no-store" in r.headers.get("Cache-Control", ""), (
        "wizard GET must opt out of bfcache via Cache-Control: no-store"
    )
