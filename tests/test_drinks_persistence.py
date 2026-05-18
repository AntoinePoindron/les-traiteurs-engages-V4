"""Red/green tests for the wizard step-5 drinks persistence.

Original bug: the 7 step-5 checkboxes were rendered in the wizard but
not persisted anywhere — POST→DB→GET dropped the selection on the
floor and the detail page always rendered "Sans alcool". This file
exercises the full chain so a future refactor that loses the column,
the applier, or the template echo trips a red assertion.

Three properties are checked per scenario:
  - the `drinks` JSON list mirrors the POSTed checkbox set,
  - the derived `drinks_alcohol` flag matches the alcoholic subset,
  - a GET on the edit page re-renders the saved selection so the
    user can iterate without re-typing.

Test isolation: the `traiteurs_test` DB is rebuilt once per pytest
session, so other tests in the suite may leave QuoteRequest rows in
place. We grab the new row from each POST's redirect Location and
clean up only what we created — a table-wide truncate would crash on
the FK refs from quotes / QRCs that other tests own.
"""

import re
import uuid


_REDIRECT_QR_ID = re.compile(r"/client/requests/([0-9a-f-]{36})")


def _qr_id_from_redirect(response) -> uuid.UUID | None:
    """Extract the new QR's UUID from a 302 Location pointing at
    `/client/requests/<id>` (or `/edit` for the post-edit redirect).
    Returns None if the redirect went elsewhere."""
    location = response.headers.get("Location", "")
    m = _REDIRECT_QR_ID.search(location)
    return uuid.UUID(m.group(1)) if m else None


def _fetch_request(qr_id):
    """Return the QuoteRequest row for `qr_id` or None."""
    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        return s.get(QuoteRequest, qr_id)
    finally:
        s.close()


def _delete_quote_requests(ids):
    """Drop ONLY the QuoteRequests this test created, by id, in a
    single statement. Direct DELETE is safe here — `POST
    /client/requests/new` doesn't seed dependent rows (quotes / QRCs
    only land via accept/qualify flows). A table-wide truncate would
    crash on FK refs from rows other tests own."""
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


def test_drinks_selection_is_persisted_on_create(client, login):
    """POST `/client/requests/new` with a mixed alcoholic+non-alcoholic
    selection must persist the slugs and flip `drinks_alcohol`."""
    login("alice@test.local")
    created: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data={
                "drinks_eau_plate": "1",
                "drinks_vins": "1",
                "drinks_champagne": "1",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302, r.data
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None, (
            f"POST must redirect to /client/requests/<id>; got "
            f"Location={r.headers.get('Location')!r}"
        )
        created.add(new_id)

        qr = _fetch_request(new_id)
        assert qr is not None, "POST must have created a QuoteRequest"
        assert set(qr.drinks or []) == {
            "drinks_eau_plate",
            "drinks_vins",
            "drinks_champagne",
        }, f"persisted drinks={qr.drinks!r}"
        assert qr.drinks_alcohol is True, (
            "drinks_alcohol must be True when an alcoholic slug is selected"
        )
    finally:
        _delete_quote_requests(created)


def test_non_alcoholic_only_selection_keeps_drinks_alcohol_false(client, login):
    """All-soft selection (eau / soft / boissons chaudes) must NOT flip
    `drinks_alcohol` — that's the whole point of deriving it server-side."""
    login("alice@test.local")
    created: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data={
                "drinks_eau_plate": "1",
                "drinks_soft": "1",
                "drinks_boissons_chaudes": "1",
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None
        created.add(new_id)

        qr = _fetch_request(new_id)
        assert qr is not None
        assert qr.drinks_alcohol is False, (
            "drinks_alcohol must stay False when no alcoholic slug is selected"
        )
    finally:
        _delete_quote_requests(created)


def test_empty_selection_persists_drinks_as_null(client, login):
    """A submit with zero ticked drinks must store NULL, not `[]`, so
    the DB stays consistent with the "no answer yet" semantics already
    used by the rest of the column set."""
    login("alice@test.local")
    created: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data={},
            follow_redirects=False,
        )
        assert r.status_code == 302
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None
        created.add(new_id)

        qr = _fetch_request(new_id)
        assert qr is not None
        assert qr.drinks is None, (
            f"empty selection must store NULL (got {qr.drinks!r}), so "
            "templates can distinguish 'no answer' from 'water-only'"
        )
        assert qr.drinks_alcohol is False
    finally:
        _delete_quote_requests(created)


def test_forged_zero_value_does_not_count_as_ticked(client, login):
    """A forged POST with `drinks_vins=0` (manually crafted; the real
    HTML checkbox emits nothing when unticked) must NOT smuggle the
    slug in. Guards against a subtle truthy-string bug where `"0"` is
    accepted as a truthy form value."""
    login("alice@test.local")
    created: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data={"drinks_vins": "0"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None
        created.add(new_id)

        qr = _fetch_request(new_id)
        assert qr is not None
        assert (qr.drinks or []) == [], (
            f"drinks_vins=0 must not be treated as ticked (got {qr.drinks!r})"
        )
        assert qr.drinks_alcohol is False
    finally:
        _delete_quote_requests(created)


def test_edit_page_pre_ticks_the_saved_selection(client, login):
    """Loading the edit page for a previously-saved request must
    re-tick the boxes — that's the bug the original PR fixed."""
    login("alice@test.local")
    created: set[uuid.UUID] = set()
    try:
        r = client.post(
            "/client/requests/new",
            data={"drinks_eau_plate": "1", "drinks_bieres": "1"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        new_id = _qr_id_from_redirect(r)
        assert new_id is not None
        created.add(new_id)

        r = client.get(f"/client/requests/{new_id}/edit")
        assert r.status_code == 200, r.data
        html = r.data.decode("utf-8", errors="replace")
        # Both saved slugs must come back rendered as `checked` in the
        # form so the user can iterate.
        assert 'name="drinks_eau_plate"' in html and "checked" in html, (
            "edit page must pre-tick a previously-saved soft drink"
        )
        assert 'name="drinks_bieres"' in html, (
            "edit page must surface the alcohol checkbox too"
        )
    finally:
        _delete_quote_requests(created)
