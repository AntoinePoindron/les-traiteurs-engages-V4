"""Tests for H-2 (login state oracle) and H-5 (CLI reset-password
session invalidation) — both from the 2026-05-13 security audit.

H-2: the login flash distinguished `is_active=False` / `pending` /
     `rejected` with three different copy strings, giving an attacker
     with a leaked password a side-channel to map HR state and SIRET
     membership. All three must now produce identical HTML.

H-5: `flask admin reset-password` did not bump `password_changed_at`,
     so the very command an ops engineer reaches for when a session
     is compromised left the attacker's session valid. Same gap for
     `flask admin create` (a fresh admin had `password_changed_at=NULL`
     which silently disabled the session-invalidation tripwire on the
     first rotation).
"""

from __future__ import annotations

from sqlalchemy import select

# ---------------------------------------------------------------------------
# H-5 — CLI must bump password_changed_at on every password mutation
# ---------------------------------------------------------------------------


def _make_super_admin(email: str, password: str = "OldPw!Old!Pw!1234"):
    """Seed a super_admin so reset-password has a target. Uses a real
    bcrypt hash because validate_password() etc. checks the policy at
    runtime. Returns (user_id, initial password_changed_at)."""
    import bcrypt
    from database import session_factory
    from models import User, UserRole

    s = session_factory()
    try:
        existing = s.scalar(select(User).where(User.email == email))
        if existing:
            s.delete(existing)
            s.commit()
        user = User(
            email=email,
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            first_name="Test",
            last_name="Admin",
            role=UserRole.super_admin,
            is_active=True,
            # NOT setting password_changed_at — that's exactly the legacy
            # state of accounts in prod before this PR. The test verifies
            # we go from NULL → non-NULL on reset.
        )
        s.add(user)
        s.commit()
        return user.id, user.password_changed_at
    finally:
        s.close()


def test_cli_reset_password_bumps_password_changed_at(app):
    """The `flask admin reset-password` CLI must update
    `password_changed_at` so existing sessions are invalidated. The
    audit PoC: an attacker who's already in must lose their cookie at
    the next request after ops fires the reset. The session check in
    `app.load_current_user` compares `session["pwd_changed_at"]` against
    the live column; if the column is stale, the attacker stays in."""
    from cli import reset_password
    from database import session_factory
    from models import User

    email = "h5-reset@test.local"
    user_id, before = _make_super_admin(email)
    assert before is None, (
        "fixture left password_changed_at non-null — the test no longer covers "
        "the NULL→value transition we care about"
    )

    runner = app.test_cli_runner()
    # `_read_password_twice` prompts twice + validates policy; supply a
    # policy-compliant value on both lines.
    new_pw = "ReplacedNow1234!"
    result = runner.invoke(reset_password, [email], input=f"{new_pw}\n{new_pw}\n")
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"

    s = session_factory()
    try:
        u = s.get(User, user_id)
        assert u.password_changed_at is not None, (
            "reset-password did NOT bump password_changed_at — the regression "
            "the audit H-5 flagged is still present"
        )
    finally:
        s.close()


def test_cli_create_admin_stamps_password_changed_at(app):
    """A freshly-created super-admin must have `password_changed_at`
    set so the *first* rotation correctly invalidates that admin's
    sessions. Leaving it NULL means the comparison
    `session["pwd_changed_at"] != live` would be `None == None` after
    the first reset (the field was NULL going in), and the session
    survives. Audit H-5 secondary recommendation."""
    from cli import create_admin
    from database import session_factory
    from models import User

    email = "h5-fresh@test.local"
    # Wipe any leftover from a prior run.
    s = session_factory()
    try:
        existing = s.scalar(select(User).where(User.email == email))
        if existing:
            s.delete(existing)
            s.commit()
    finally:
        s.close()

    runner = app.test_cli_runner()
    pw = "FreshPolicyPw99!"
    result = runner.invoke(
        create_admin,
        ["--email", email, "--first-name", "H5", "--last-name", "Fresh"],
        input=f"{pw}\n{pw}\n",
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"

    s = session_factory()
    try:
        u = s.scalar(select(User).where(User.email == email))
        assert u is not None
        assert u.password_changed_at is not None, (
            "create_admin did NOT stamp password_changed_at — first reset "
            "would not invalidate sessions"
        )
    finally:
        s.close()


# ---------------------------------------------------------------------------
# H-2 — the three inactive-account flashes must collapse to one
# ---------------------------------------------------------------------------


def _seed_user_in_state(*, email: str, is_active: bool, membership):
    """Seed a user in a specific (is_active, membership_status) combo.
    Returns the password used."""
    import bcrypt
    from sqlalchemy import select

    from database import session_factory
    from models import Company, User, UserRole

    password = "OracleTestPw!42"
    s = session_factory()
    try:
        company = s.scalar(select(Company).where(Company.siret == "12345678901234"))
        existing = s.scalar(select(User).where(User.email == email))
        if existing:
            s.delete(existing)
            s.commit()
        u = User(
            email=email,
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            first_name="O",
            last_name="O",
            role=UserRole.client_user,
            company_id=company.id,
            is_active=is_active,
            membership_status=membership,
        )
        s.add(u)
        s.commit()
        return password
    finally:
        s.close()


def _extract_flash_block(html: str) -> str:
    """Return the snippet of HTML that the user sees as the login-page
    flash. We use this to compare three responses byte-for-byte minus
    request-bound noise (CSRF token, server timestamps).

    The flash markup lives in components/flash_messages.html as a
    `<div role="alert">...</div>`. Falling back to the whole body if the
    role marker isn't found so the assertion still has something to
    compare on rather than silently passing."""
    import re

    m = re.search(r'<div[^>]*role="alert"[^>]*>.*?</div>', html, flags=re.DOTALL)
    return m.group(0) if m else html


def test_login_flash_identical_for_all_inactive_states(client):
    """Three independently-inactive accounts (disabled / pending /
    rejected) must produce the same flash markup at login time. The
    audit's CWE-204 oracle is exactly this difference being readable."""
    from models import MembershipStatus

    cases = [
        ("oracle-disabled@test.local", False, MembershipStatus.active),
        ("oracle-pending@test.local", True, MembershipStatus.pending),
        ("oracle-rejected@test.local", True, MembershipStatus.rejected),
    ]

    flashes: list[str] = []
    for email, active, membership in cases:
        password = _seed_user_in_state(
            email=email, is_active=active, membership=membership
        )
        r = client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=False,
        )
        assert r.status_code == 200, (
            f"non-200 for {email}: got {r.status_code}, leaks state on its own"
        )
        flashes.append(_extract_flash_block(r.data.decode("utf-8", errors="replace")))

    # All three must be byte-identical. If a future refactor reintroduces
    # any state-specific copy this assertion goes red.
    assert flashes[0] == flashes[1] == flashes[2], (
        "login flash MUST be identical across inactive states; got distinct "
        "payloads:\n - disabled:\n"
        + flashes[0]
        + "\n - pending:\n"
        + flashes[1]
        + "\n - rejected:\n"
        + flashes[2]
    )


def test_login_flash_does_not_leak_state_keywords(client):
    """Belt-and-suspenders: even if the bodies happen to coincide
    today, ban the specific words ('desactive', 'rattachement',
    'refusee', 'en attente') so a careless reintroduction is caught."""
    from models import MembershipStatus

    password = _seed_user_in_state(
        email="oracle-keyword@test.local",
        is_active=False,
        membership=MembershipStatus.active,
    )
    r = client.post(
        "/login",
        data={"email": "oracle-keyword@test.local", "password": password},
        follow_redirects=False,
    )
    body = r.data.decode("utf-8", errors="replace").lower()
    for forbidden in ("desactive", "rattachement", "refus", "en attente"):
        assert forbidden not in body, (
            f"flash leaks the '{forbidden}' keyword — H-2 oracle is back"
        )
