"""Integration tests for the team self-delete + invite-link feature
(branch feat/no-self-delete-effectifs).

Covers:
- Server-side self-delete guard on team_employee_delete (defense-in-depth
  for the disabled trash button in the UI).
- Invite token lifecycle: rotation, revocation, redemption, single-use,
  TTL expiry. Tokens are unguessable (~256 bits) so we don't test
  brute-force; we test the state-machine.
- /signup/invite/<token> contract: email + name come from the
  CompanyEmployee row, never from POST data.
- Duplicate-email guard on team_employee_create.
- team_approve clears any stale invite token when it links an existing
  row (regression for the review-fix in commit 5b3518b).
- own_requests_filter: client_admin sees the company's QuoteRequests,
  client_user sees only their own.

Tests use distinct emails per case to stay independent of session state
across the suite.
"""

import datetime as _dt
import re as _re

import bcrypt
from sqlalchemy import select


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _acme_id():
    from database import session_factory
    from models import Company

    s = session_factory()
    try:
        return s.scalar(select(Company).where(Company.siret == "12345678901234")).id
    finally:
        s.close()


def _alice_id():
    from database import session_factory
    from models import User

    s = session_factory()
    try:
        return s.scalar(select(User).where(User.email == "alice@test.local")).id
    finally:
        s.close()


def _bob_id():
    from database import session_factory
    from models import User

    s = session_factory()
    try:
        return s.scalar(select(User).where(User.email == "bob@test.local")).id
    finally:
        s.close()


def _ensure_employee(email, *, user_id=None, invite_token=None, invited_at=None):
    """Idempotent: create or update a CompanyEmployee under ACME with the
    given fields. Returns its id (UUID)."""
    from database import session_factory
    from models import CompanyEmployee

    company_id = _acme_id()
    s = session_factory()
    try:
        row = s.scalar(
            select(CompanyEmployee).where(
                CompanyEmployee.company_id == company_id,
                CompanyEmployee.email == email,
            )
        )
        if row is None:
            row = CompanyEmployee(
                company_id=company_id,
                first_name="Test",
                last_name="Employee",
                email=email,
            )
            s.add(row)
        row.user_id = user_id
        row.invite_token = invite_token
        row.invited_at = invited_at
        s.commit()
        return row.id
    finally:
        s.close()


def _fetch_employee(employee_id):
    from database import session_factory
    from models import CompanyEmployee

    s = session_factory()
    try:
        return s.get(CompanyEmployee, employee_id)
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Self-delete protection
# ---------------------------------------------------------------------------


def test_admin_cannot_delete_own_effectifs_row(client, login):
    """Server-side guard for the disabled trash button: even a tampered
    POST that targets the admin's own row must leave it intact."""
    row_id = _ensure_employee("alice-self@test.local", user_id=_alice_id())

    login("alice@test.local")
    resp = client.post(
        f"/client/team/employees/{row_id}/delete", follow_redirects=False
    )
    assert resp.status_code == 302
    assert _fetch_employee(row_id) is not None, (
        "self-delete must not remove the admin's own effectifs row"
    )


def test_admin_can_delete_other_effectifs_row(client, login):
    """Regression: the self-delete guard must not break the normal
    'delete a colleague' path. The colleague is linked to bob's user
    account (not user_id=None) so we exercise the realistic case where
    the guard's `employee.user_id == user.id` check has a non-null LHS
    that simply differs from the admin's id."""
    row_id = _ensure_employee("colleague-to-delete@test.local", user_id=_bob_id())

    login("alice@test.local")
    resp = client.post(
        f"/client/team/employees/{row_id}/delete", follow_redirects=False
    )
    assert resp.status_code == 302
    assert _fetch_employee(row_id) is None, "non-self deletes must still work"


# ---------------------------------------------------------------------------
# Invite token lifecycle
# ---------------------------------------------------------------------------


def test_create_employee_generates_invite_token(client, login):
    """team_employee_create must mint an unguessable token + invited_at,
    and redirect with ?invite=<id> so the modal pops on next render."""
    login("alice@test.local")
    resp = client.post(
        "/client/team/employees",
        data={
            "first_name": "Newbie",
            "last_name": "Tester",
            "email": "newbie-create@example.com",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "invite=" in resp.headers["Location"], (
        "redirect must carry ?invite=<id> so the team page can pop the modal"
    )

    from database import session_factory
    from models import CompanyEmployee

    s = session_factory()
    try:
        row = s.scalar(
            select(CompanyEmployee).where(
                CompanyEmployee.email == "newbie-create@example.com"
            )
        )
        assert row is not None
        # secrets.token_urlsafe(32) → 43 chars in [A-Za-z0-9_-]; assert
        # the exact shape so a regression to a weaker generator (literal
        # string, counter, predictable hash) fails the test.
        assert row.invite_token is not None
        assert len(row.invite_token) == 43, (
            f"expected 43-char urlsafe token, got len={len(row.invite_token)}"
        )
        assert _re.fullmatch(r"[A-Za-z0-9_-]+", row.invite_token), (
            "token must use the urlsafe alphabet"
        )
        assert row.invited_at is not None
        assert row.user_id is None
    finally:
        s.close()


def test_invite_rotation_changes_token(client, login):
    """Re-POSTing /invite on an already-invited row rotates the token —
    needed when the previous link leaks."""
    employee_id = _ensure_employee(
        "rotate-target@test.local",
        invite_token="initial-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        invited_at=_dt.datetime.utcnow(),
    )
    before = _fetch_employee(employee_id).invite_token

    login("alice@test.local")
    resp = client.post(
        f"/client/team/employees/{employee_id}/invite", follow_redirects=False
    )
    assert resp.status_code == 302

    after = _fetch_employee(employee_id).invite_token
    assert after and after != before, "rotation must produce a fresh token"
    # Same shape constraints as fresh generation — a deterministic-but-
    # different value (e.g. a counter) would slip through `after != before`.
    assert len(after) == 43, f"rotated token wrong length: {len(after)}"
    assert _re.fullmatch(r"[A-Za-z0-9_-]+", after), (
        "rotated token must use the urlsafe alphabet"
    )


def test_invite_revoke_clears_token(client, login):
    employee_id = _ensure_employee(
        "revoke-target@test.local",
        invite_token="some-live-token-yyyyyyyyyyyyyyyyyyyyyyyyyyy",
        invited_at=_dt.datetime.utcnow(),
    )

    login("alice@test.local")
    resp = client.post(
        f"/client/team/employees/{employee_id}/invite/revoke",
        follow_redirects=False,
    )
    assert resp.status_code == 302

    row = _fetch_employee(employee_id)
    assert row.invite_token is None
    assert row.invited_at is None


def test_invite_for_already_linked_employee_is_noop(client, login):
    """An employee already attached to a User shouldn't get a new token.
    Assert *both* token and invited_at stay untouched so a regression that
    silently sets invited_at without minting a token still fails."""
    employee_id = _ensure_employee("already-linked@test.local", user_id=_bob_id())

    login("alice@test.local")
    client.post(f"/client/team/employees/{employee_id}/invite", follow_redirects=False)
    row = _fetch_employee(employee_id)
    assert row.invite_token is None, "must not mint a token for a linked employee"
    assert row.invited_at is None, "must not stamp invited_at for a linked employee"


# ---------------------------------------------------------------------------
# /signup/invite/<token> redemption
# ---------------------------------------------------------------------------


def test_signup_invite_get_renders_form_for_valid_token(client):
    token = "valid-redeem-token-aaaaaaaaaaaaaaaaaaaaaaaaaa"
    _ensure_employee(
        "redeem-form@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )
    resp = client.get(f"/signup/invite/{token}")
    assert resp.status_code == 200
    assert b"redeem-form@test.local" in resp.data


def test_signup_invite_invalid_token_returns_404(client):
    resp = client.get("/signup/invite/this-token-does-not-exist")
    assert resp.status_code == 404


def test_signup_invite_expired_token_returns_404(client):
    """invited_at older than INVITE_TOKEN_TTL_DAYS (7d) → token is dead."""
    token = "expired-token-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    _ensure_employee(
        "expired@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow() - _dt.timedelta(days=8),
    )
    resp = client.get(f"/signup/invite/{token}")
    assert resp.status_code == 404


def test_signup_invite_redemption_creates_user_and_consumes_token(client):
    token = "good-redeem-token-cccccccccccccccccccccccccc"
    employee_id = _ensure_employee(
        "redeem-success@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )
    resp = client.post(
        f"/signup/invite/{token}",
        data={"password": "VeryStrongPassword1!"},
        follow_redirects=False,
    )
    assert resp.status_code == 302, (
        f"successful redemption must redirect to dashboard; got {resp.status_code}"
    )

    from database import session_factory
    from models import MembershipStatus, User, UserRole

    s = session_factory()
    try:
        u = s.scalar(select(User).where(User.email == "redeem-success@test.local"))
        assert u is not None, "redemption must create the user"
        assert u.role == UserRole.client_user
        assert u.membership_status == MembershipStatus.active, (
            "invite-flow signup bypasses pending-approval"
        )
        assert u.company_id == _acme_id()
    finally:
        s.close()

    row = _fetch_employee(employee_id)
    assert row.user_id is not None
    assert row.invite_token is None, "token must be cleared on redemption"


def test_signup_invite_token_is_single_use(client):
    """Once redeemed, the same token must fail re-redemption with 404."""
    token = "single-use-token-ddddddddddddddddddddddddddd"
    _ensure_employee(
        "single-use@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )

    first = client.post(
        f"/signup/invite/{token}",
        data={"password": "FirstUseStrong1!"},
        follow_redirects=False,
    )
    assert first.status_code == 302

    # Different test client to drop the session set by first redemption.
    fresh = client.application.test_client()
    second = fresh.get(f"/signup/invite/{token}")
    assert second.status_code == 404


def test_signup_invite_ignores_tampered_email_in_post(client):
    """Even if the POST body smuggles a different email/name, the user
    must be created with the values stored on the CompanyEmployee row."""
    token = "tamper-test-token-eeeeeeeeeeeeeeeeeeeeeeeeee"
    _ensure_employee(
        "real-email@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )
    resp = client.post(
        f"/signup/invite/{token}",
        data={
            "password": "TamperResistant1!",
            "email": "evil@attacker.tld",
            "first_name": "Mallory",
            "last_name": "Hacker",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        good = s.scalar(select(User).where(User.email == "real-email@test.local"))
        evil = s.scalar(select(User).where(User.email == "evil@attacker.tld"))
        assert good is not None, "user must be created with the row's email"
        assert evil is None, "tampered email must be ignored, not honored"
    finally:
        s.close()


def test_signup_invite_weak_password_rejected(client):
    token = "weak-pw-token-ffffffffffffffffffffffffffffff"
    _ensure_employee(
        "weak-pw@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )
    resp = client.post(
        f"/signup/invite/{token}",
        data={"password": "short"},
        follow_redirects=False,
    )
    # validate_password rejects → form re-rendered, token still alive.
    assert resp.status_code == 200

    from database import session_factory
    from models import User

    s = session_factory()
    try:
        u = s.scalar(select(User).where(User.email == "weak-pw@test.local"))
        assert u is None, "weak password must not create the user"
    finally:
        s.close()


def test_signup_invite_collision_with_existing_user_redirects_to_login(client):
    """If a User with the row's email already exists (e.g., separate signup
    landed first), redemption must surface a clean message and redirect to
    /login — no 500."""
    token = "collision-token-ggggggggggggggggggggggggggg"
    _ensure_employee(
        "preexisting@test.local",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )
    # Pre-create the User out of band to simulate the collision.
    from database import session_factory
    from models import MembershipStatus, User, UserRole

    s = session_factory()
    try:
        if s.scalar(select(User).where(User.email == "preexisting@test.local")) is None:
            s.add(
                User(
                    email="preexisting@test.local",
                    password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
                    first_name="Pre",
                    last_name="Existing",
                    role=UserRole.client_user,
                    company_id=_acme_id(),
                    membership_status=MembershipStatus.active,
                )
            )
            s.commit()
    finally:
        s.close()

    resp = client.post(
        f"/signup/invite/{token}",
        data={"password": "AnotherStrongOne1!"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_signup_invite_handles_integrity_error_at_flush(client, monkeypatch):
    """Race-condition path of the review fix: if a parallel signup grabs
    the User.email between the pre-check `select` and the flush, libpq
    raises IntegrityError. The handler must catch it, rollback, and
    redirect to /login — not 500.

    Simulated by monkey-patching Session.flush to raise IntegrityError
    only when the racing User is in `session.new`. The pre-check
    `db.scalar(select(User)...)` runs *before* anything is added so
    autoflush at that point has no pending changes and is unaffected.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    token = "race-token-iiiiiiiiiiiiiiiiiiiiiiiiiiiii"
    employee_id = _ensure_employee(
        "race-flush@example.com",
        invite_token=token,
        invited_at=_dt.datetime.utcnow(),
    )

    real_flush = Session.flush
    fired = {"n": 0}

    def patched_flush(self, *args, **kwargs):
        # Only intercept the flush that's about to persist *our* User.
        # Any housekeeping flush from elsewhere falls through to the real
        # implementation.
        for obj in self.new:
            if getattr(obj, "email", None) == "race-flush@example.com":
                fired["n"] += 1
                raise IntegrityError(
                    "simulated race on users.email",
                    None,
                    Exception("duplicate key"),
                )
        return real_flush(self, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", patched_flush)

    resp = client.post(
        f"/signup/invite/{token}",
        data={"password": "RaceResistantPwd1!"},
        follow_redirects=False,
    )

    assert fired["n"] >= 1, "simulated IntegrityError must have been triggered"
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"], (
        f"expected redirect to /login, got {resp.headers.get('Location')}"
    )

    # Rollback must preserve the row's pre-redemption state — the token
    # stays alive so the legitimate invitee can still complete signup
    # after the race resolves, and user_id is not linked to the
    # never-persisted User.
    row = _fetch_employee(employee_id)
    assert row.invite_token == token, "rollback must preserve the invite token"
    assert row.user_id is None


# ---------------------------------------------------------------------------
# Duplicate-email guard (review fix)
# ---------------------------------------------------------------------------


def test_create_employee_rejects_duplicate_email_in_company(client, login):
    _ensure_employee("dup-target@example.com")

    login("alice@test.local")
    resp = client.post(
        "/client/team/employees",
        data={
            "first_name": "Duplicate",
            "last_name": "Attempt",
            "email": "dup-target@example.com",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302  # redirect with error flash

    from database import session_factory
    from models import CompanyEmployee

    s = session_factory()
    try:
        rows = s.scalars(
            select(CompanyEmployee).where(
                CompanyEmployee.company_id == _acme_id(),
                CompanyEmployee.email == "dup-target@example.com",
            )
        ).all()
        assert len(rows) == 1, "duplicate email in same company must be rejected"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# team_approve clears stale invite token (review fix)
# ---------------------------------------------------------------------------


def test_approve_clears_stale_invite_token_on_existing_row(client, login):
    """If admin pre-creates an invite for someone who later signs up via
    the SIRET pending flow, approving them must link the row AND wipe
    the now-dead invite token (would burn the unique index slot otherwise)."""
    pending_email = "approve-stale@test.local"

    # Pre-create the admin-side invite row.
    employee_id = _ensure_employee(
        pending_email,
        invite_token="stale-token-hhhhhhhhhhhhhhhhhhhhhhhhhh",
        invited_at=_dt.datetime.utcnow(),
    )

    # Create the matching pending User as if they signed up through SIRET.
    from database import session_factory
    from models import MembershipStatus, User, UserRole

    s = session_factory()
    try:
        if s.scalar(select(User).where(User.email == pending_email)) is None:
            s.add(
                User(
                    email=pending_email,
                    password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
                    first_name="Pending",
                    last_name="Member",
                    role=UserRole.client_user,
                    company_id=_acme_id(),
                    membership_status=MembershipStatus.pending,
                )
            )
            s.commit()
        pending_user_id = s.scalar(select(User.id).where(User.email == pending_email))
    finally:
        s.close()

    login("alice@test.local")
    resp = client.post(
        f"/client/team/approve/{pending_user_id}", follow_redirects=False
    )
    assert resp.status_code == 302

    row = _fetch_employee(employee_id)
    assert row.user_id == pending_user_id, "row must link to the approved user"
    assert row.invite_token is None, "stale invite token must be cleared"
    assert row.invited_at is None


# ---------------------------------------------------------------------------
# own_requests_filter scoping
# ---------------------------------------------------------------------------


def _seed_quote_request(user_id):
    """Add a QuoteRequest under ACME owned by user_id. Returns its id."""
    from database import session_factory
    from models import QuoteRequest, QuoteRequestStatus

    s = session_factory()
    try:
        qr = QuoteRequest(
            company_id=_acme_id(),
            user_id=user_id,
            guest_count=10,
            status=QuoteRequestStatus.draft,
            event_address="1 rue Test",
            event_city="Paris",
            event_zip_code="75001",
            event_date=_dt.date.today() + _dt.timedelta(days=30),
        )
        s.add(qr)
        s.commit()
        return qr.id
    finally:
        s.close()


def test_client_user_sees_only_own_requests(client, login):
    """bob (client_user) must only see his own QuoteRequests on
    /client/requests, not those created by other users in the same
    company."""
    alice_qr = _seed_quote_request(_alice_id())
    bob_qr = _seed_quote_request(_bob_id())

    login("bob@test.local")
    resp = client.get("/client/requests")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert str(bob_qr) in body, "bob must see his own QR"
    assert str(alice_qr) not in body, (
        "client_user must not see another company member's QR"
    )


def test_client_admin_sees_all_company_requests(client, login):
    """Symmetric guard: alice (client_admin) must still see the full
    company-wide list."""
    alice_qr = _seed_quote_request(_alice_id())
    bob_qr = _seed_quote_request(_bob_id())

    login("alice@test.local")
    resp = client.get("/client/requests")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8", errors="replace")
    assert str(bob_qr) in body, "admin must see colleagues' QRs"
    assert str(alice_qr) in body, "admin must see her own QRs"


def test_client_user_cannot_load_other_users_request_detail(client, login):
    """get_company_request must 404 for a client_user trying to open a
    QR they didn't create — even within their own company."""
    alice_qr = _seed_quote_request(_alice_id())

    login("bob@test.local")
    resp = client.get(f"/client/requests/{alice_qr}", follow_redirects=False)
    assert resp.status_code == 404, (
        f"client_user must 404 on a colleague's QR; got {resp.status_code}"
    )
