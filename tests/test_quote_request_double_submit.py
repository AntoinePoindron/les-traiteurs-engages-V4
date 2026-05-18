"""Red/green tests for the wizard double-submit guard.

Original bug: pressing Back after submitting the wizard restored the
cached form, the user re-clicked Submit, and a duplicate QuoteRequest
was persisted. The fix wires three layers of defence; this file
exercises the *server* one — a stable, browser-independent assertion
that the same idempotency token can never persist twice.

Each test rebuilds an isolated wizard payload so the suite stays
independent from anything else in `traiteurs_test`. Wipe is run in
`try/finally` to keep the database clean between runs.
"""

import uuid


def _wipe_quote_requests():
    """Drop every QuoteRequest so token-uniqueness assertions don't
    drift across test runs."""
    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        s.execute(QuoteRequest.__table__.delete())
        s.commit()
    finally:
        s.close()


def _count_quote_requests():
    """How many rows currently sit in `quote_requests`."""
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
        first_location = first.headers["Location"]
        assert _count_quote_requests() == 1, (
            "first submit should have created exactly one QuoteRequest"
        )

        second = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(token),
            follow_redirects=False,
        )
        assert second.status_code == 302, (
            f"replay must redirect to the existing detail; got {second.status_code}"
        )
        assert second.headers["Location"] == first_location, (
            "replay should point at the same detail page, not spawn a new one"
        )
        assert _count_quote_requests() == 1, (
            "a replayed form_token must NOT create a second QuoteRequest"
        )
    finally:
        _wipe_quote_requests()


def test_post_without_form_token_creates_a_quote_request(client, login):
    """Backwards-compat: a POST that omits the token (legacy form
    cached in a long-lived tab, or an older client) still goes through.
    The idempotency guard is opt-in via the hidden field."""
    login("alice@test.local")
    try:
        r = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload(None),
            follow_redirects=False,
        )
        assert r.status_code == 302, (
            f"token-less submit must still create a request; got {r.status_code}"
        )
        assert _count_quote_requests() == 1
    finally:
        _wipe_quote_requests()


def test_malformed_form_token_falls_back_to_legacy_path(client, login):
    """A malformed token (anything that fails `uuid.UUID(...)`) is
    treated as no token at all. We explicitly accept this so a tampered
    payload can't 500 the wizard — the CSRF token is the real anti-replay
    guard for malicious flows."""
    login("alice@test.local")
    try:
        r = client.post(
            "/client/requests/new",
            data=_minimal_wizard_payload("not-a-uuid"),
            follow_redirects=False,
        )
        assert r.status_code == 302, (
            f"malformed token must fall back, not 500; got {r.status_code}"
        )
        assert _count_quote_requests() == 1
    finally:
        _wipe_quote_requests()


def test_two_distinct_tokens_create_two_quote_requests(client, login):
    """Sanity check the guard isn't too aggressive: two GENUINE new
    submissions (each with its own token, as a fresh GET would issue)
    must each produce their own row. This is the "double tab" / "user
    started a new wizard" scenario the PR explicitly preserves."""
    login("alice@test.local")
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
        assert _count_quote_requests() == 2, (
            "two distinct tokens must produce two QuoteRequest rows"
        )
    finally:
        _wipe_quote_requests()


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
