"""Tests for /admin/requests — the super_admin requests registry.

Verifies the three guard rails the review flagged as missing:
  1. Role gate — only super_admin reaches a 200; other roles bounce.
  2. Allow-list on `?status=` — unknown / tampered values silently
     fall back to "all" without leaking a SQL error.
  3. Pagination — large datasets stay paged at 25 rows / page; an
     out-of-range `?page=` clamps to the last page rather than 404.
"""


import uuid


def _seed_request(status):
    """Insert one QuoteRequest with the given status, owned by ACME Test.
    Returns the new id so the caller can assert on it."""
    import datetime as _dt

    from sqlalchemy import select

    from database import session_factory
    from models import (
        Company,
        MealType,
        QuoteRequest,
        QuoteRequestStatus,
        User,
    )

    s = session_factory()
    try:
        acme = s.scalar(select(Company).where(Company.siret == "12345678901234"))
        alice = s.scalar(select(User).where(User.email == "alice@test.local"))
        qr = QuoteRequest(
            company_id=acme.id,
            user_id=alice.id,
            meal_type=MealType.plateaux_repas,
            event_date=_dt.date.today() + _dt.timedelta(days=30),
            guest_count=10,
            status=status,
        )
        s.add(qr)
        s.commit()
        return qr.id
    finally:
        s.close()


def _wipe_test_requests():
    """Drop every QuoteRequest seeded in this module so the count
    assertions don't drift across test runs."""
    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        s.execute(QuoteRequest.__table__.delete())
        s.commit()
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Role gate
# ---------------------------------------------------------------------------


def test_super_admin_can_reach_the_requests_list(client, login):
    login("admin@test.local")
    r = client.get("/admin/requests")
    assert r.status_code == 200, r.data


def test_client_admin_is_forbidden(client, login):
    login("alice@test.local")
    r = client.get("/admin/requests")
    assert r.status_code in (302, 403), (
        f"client_admin must not reach /admin/requests; got {r.status_code}"
    )


def test_caterer_is_forbidden(client, login):
    login("cook@test.local")
    r = client.get("/admin/requests")
    assert r.status_code in (302, 403), (
        f"caterer must not reach /admin/requests; got {r.status_code}"
    )


def test_anonymous_is_bounced_to_login(client):
    r = client.get("/admin/requests", follow_redirects=False)
    assert r.status_code in (302, 401, 403), (
        f"anonymous user must be bounced; got {r.status_code}"
    )


# ---------------------------------------------------------------------------
# Allow-list on ?status=
# ---------------------------------------------------------------------------


def test_unknown_status_falls_back_to_all(client, login):
    """A tampered `?status=` value must not 500 — it silently degrades
    to the "all" tab so an attacker probing for SQL errors gets nothing
    interesting back."""
    from models import QuoteRequestStatus

    qr_id = _seed_request(QuoteRequestStatus.pending_review)
    try:
        login("admin@test.local")
        # Garbage value that's nowhere near any status enum.
        r = client.get("/admin/requests?status=' OR 1=1")
        assert r.status_code == 200, r.data
        # The seeded pending row should be visible under the fallback "all".
        assert str(qr_id)[:8].encode() in r.data or b"pending" in r.data.lower(), (
            "fallback to 'all' should still surface every status"
        )
    finally:
        _wipe_test_requests()


def test_approved_tab_is_addressable(client, login):
    """Audit follow-up: `approved` used to be missing from the tabs."""
    from models import QuoteRequestStatus

    _seed_request(QuoteRequestStatus.approved)
    try:
        login("admin@test.local")
        r = client.get("/admin/requests?status=approved")
        assert r.status_code == 200, r.data
        assert b"Approuv" in r.data, (
            "the 'Approuvées' tab must render its label so an admin "
            "knows the filter took effect"
        )
    finally:
        _wipe_test_requests()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_caps_each_page_at_25_rows(client, login):
    """The route must hard-cap to 25 rows/page so a large dataset
    doesn't OOM the worker. Seed 30 rows, expect the first page to
    surface a "page 1 / 2" hint."""
    from models import QuoteRequestStatus

    try:
        for _ in range(30):
            _seed_request(QuoteRequestStatus.completed)

        login("admin@test.local")
        r = client.get("/admin/requests?status=completed")
        assert r.status_code == 200, r.data
        # The header line announces "30 demandes · page 1 / 2".
        assert b"30 demande" in r.data
        assert b"page 1 / 2" in r.data, (
            "with 30 rows and page size 25, the header must show 2 pages"
        )
    finally:
        _wipe_test_requests()


def test_page_out_of_range_clamps_to_last(client, login):
    """A user typing ?page=99 on a small dataset should land on the
    last real page, not get an empty list or a 404."""
    from models import QuoteRequestStatus

    try:
        _seed_request(QuoteRequestStatus.completed)
        login("admin@test.local")
        r = client.get("/admin/requests?status=completed&page=99")
        assert r.status_code == 200, r.data
        # The "Aucune demande" empty state must NOT show — the row exists.
        assert b"Aucune demande" not in r.data, (
            "out-of-range page should clamp to the last page, not render empty"
        )
    finally:
        _wipe_test_requests()


# ---------------------------------------------------------------------------
# Defense in depth: detail link still resolves for unknown UUID → 404
# ---------------------------------------------------------------------------


def test_detail_link_404s_on_unknown_uuid(client, login):
    """Adjacent guarantee: a typed-in UUID that doesn't exist must 404,
    not 500 — the detail route is reached from this list."""
    login("admin@test.local")
    r = client.get(f"/admin/qualification/{uuid.uuid4()}")
    assert r.status_code == 404, r.data
