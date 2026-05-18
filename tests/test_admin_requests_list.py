"""Tests for /admin/requests — the super_admin requests registry.

Verifies the three guard rails the review flagged as missing:
  1. Role gate — only super_admin reaches a 200; other roles bounce.
  2. Allow-list on `?status=` — unknown / tampered values silently
     fall back to "all" without leaking a SQL error.
  3. Pagination — large datasets stay paged at 25 rows / page; an
     out-of-range `?page=` clamps to the last page rather than 404.

Test isolation: the `traiteurs_test` DB is rebuilt once per pytest
session, so other tests may have left QuoteRequest rows. We track the
ids we seed and delete only those — a table-wide truncate would crash
on FK refs from quotes / QRCs other tests own. Count assertions are
relative to a baseline grabbed before seeding.
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


def _count_by_status(status) -> int:
    """Number of QuoteRequest rows currently sitting in `status`."""
    from sqlalchemy import func, select

    from database import session_factory
    from models import QuoteRequest

    s = session_factory()
    try:
        return (
            s.scalar(
                select(func.count(QuoteRequest.id)).where(QuoteRequest.status == status)
            )
            or 0
        )
    finally:
        s.close()


def _delete_quote_requests(ids):
    """Drop ONLY the QuoteRequests this test seeded. Other tests may
    hold quotes / QRCs that FK-reference QuoteRequest, so the brutal
    `DELETE FROM quote_requests` we used to do crashed on cleanup."""
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

    created: set[uuid.UUID] = set()
    try:
        qr_id = _seed_request(QuoteRequestStatus.pending_review)
        created.add(qr_id)
        login("admin@test.local")
        # Garbage value that's nowhere near any status enum.
        r = client.get("/admin/requests?status=' OR 1=1")
        assert r.status_code == 200, r.data
        # The seeded pending row should be visible under the fallback "all".
        assert str(qr_id)[:8].encode() in r.data or b"pending" in r.data.lower(), (
            "fallback to 'all' should still surface every status"
        )
    finally:
        _delete_quote_requests(created)


def test_approved_tab_is_addressable(client, login):
    """Audit follow-up: `approved` used to be missing from the tabs."""
    from models import QuoteRequestStatus

    created: set[uuid.UUID] = set()
    try:
        created.add(_seed_request(QuoteRequestStatus.approved))
        login("admin@test.local")
        r = client.get("/admin/requests?status=approved")
        assert r.status_code == 200, r.data
        assert b"Approuv" in r.data, (
            "the 'Approuvées' tab must render its label so an admin "
            "knows the filter took effect"
        )
    finally:
        _delete_quote_requests(created)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_caps_each_page_at_25_rows(client, login):
    """The route must hard-cap to 25 rows/page so a large dataset
    doesn't OOM the worker. Seed enough rows to land on at least two
    pages and confirm the header announces the right counts — the
    baseline accounts for any pre-existing `completed` rows other
    tests may have left behind."""
    from models import QuoteRequestStatus

    baseline = _count_by_status(QuoteRequestStatus.completed)
    # Seed enough so that baseline+seeded > 25 even if other tests
    # left some rows behind. 30 is the original review request and
    # also generous against drift.
    seeded = 30
    total = baseline + seeded
    expected_pages = (total + 24) // 25  # ceil(total / 25)
    created: set[uuid.UUID] = set()
    try:
        for _ in range(seeded):
            created.add(_seed_request(QuoteRequestStatus.completed))

        login("admin@test.local")
        r = client.get("/admin/requests?status=completed")
        assert r.status_code == 200, r.data
        # Header announces "<total> demandes · page 1 / <expected_pages>".
        assert f"{total} demande".encode() in r.data, (
            f"header must announce the actual completed count "
            f"({total}); body excerpt={r.data[:400]!r}"
        )
        assert f"page 1 / {expected_pages}".encode() in r.data, (
            f"with {total} rows and page size 25, header must show "
            f"{expected_pages} pages"
        )
    finally:
        _delete_quote_requests(created)


def test_page_out_of_range_clamps_to_last(client, login):
    """A user typing ?page=99 on a small dataset should land on the
    last real page, not get an empty list or a 404."""
    from models import QuoteRequestStatus

    created: set[uuid.UUID] = set()
    try:
        created.add(_seed_request(QuoteRequestStatus.completed))
        login("admin@test.local")
        r = client.get("/admin/requests?status=completed&page=99")
        assert r.status_code == 200, r.data
        # The "Aucune demande" empty state must NOT show — the row exists.
        assert b"Aucune demande" not in r.data, (
            "out-of-range page should clamp to the last page, not render empty"
        )
    finally:
        _delete_quote_requests(created)


# ---------------------------------------------------------------------------
# Defense in depth: detail link still resolves for unknown UUID → 404
# ---------------------------------------------------------------------------


def test_detail_link_404s_on_unknown_uuid(client, login):
    """Adjacent guarantee: a typed-in UUID that doesn't exist must 404,
    not 500 — the detail route is reached from this list."""
    login("admin@test.local")
    r = client.get(f"/admin/qualification/{uuid.uuid4()}")
    assert r.status_code == 404, r.data
