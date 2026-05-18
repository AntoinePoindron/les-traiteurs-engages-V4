"""Password-reset token lifecycle.

Coverage :
  * issue_token creates a row tied to the user with TTL in the future;
  * consume_token rejects unknown / expired / already-used tokens;
  * consume_token rotates the user's password hash and flips used_at;
  * kick_off_reset is idempotent on unknown emails (no row created,
    no exception);
  * the /forgot-password POST returns 200 even for unknown emails
    (no account-existence leak).

Convention d'imports lazy : `database`, `config`, et `services.*` sont
importés *à l'intérieur* des fonctions, pas au top-level. Sinon le
`engine` (et `config.DATABASE_URL`) est figé sur la DB de dev avant
que conftest ne switche sur `traiteurs_test`. Voir
`tests/test_workflow.py` pour le même pattern.
"""

import datetime as _dt
import uuid

import bcrypt
import pytest


@pytest.fixture
def session(app):
    from database import session_factory

    s = session_factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def _alice(s):
    from sqlalchemy import select

    from models import User

    alice = s.scalar(select(User).where(User.email == "alice@test.local"))
    if alice is None:
        all_emails = [u.email for u in s.scalars(select(User)).all()]
        raise AssertionError(f"alice@test.local not in test DB; saw {all_emails}")
    return alice


# --- issue_token ----------------------------------------------------------


def test_issue_token_persists_with_ttl_in_future(session):
    from sqlalchemy import select

    from models import PasswordResetToken
    from services import password_reset as pr

    alice = _alice(session)
    row, raw = pr.issue_token(session, user=alice)
    session.flush()

    assert row.user_id == alice.id
    assert row.used_at is None
    assert row.expires_at > _dt.datetime.utcnow()
    assert row.expires_at <= _dt.datetime.utcnow() + pr.RESET_TOKEN_TTL + _dt.timedelta(
        seconds=1
    )
    persisted = session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.id == row.id)
    )
    assert persisted is not None
    # The stored column must be the SHA-256 digest of the raw token, not
    # the raw value itself — the security guarantee of the hash-at-rest
    # change is that a DB leak should not expose live tokens.
    assert persisted.token == pr._hash_token(raw)
    assert persisted.token != raw


def test_issue_token_returns_unique_strings(session):
    from services import password_reset as pr

    alice = _alice(session)
    _row_a, a = pr.issue_token(session, user=alice)
    _row_b, b = pr.issue_token(session, user=alice)
    session.flush()
    assert a != b
    # `token_urlsafe(32)` => 43 chars URL-safe base64.
    assert len(a) >= 32


# --- consume_token --------------------------------------------------------


def test_consume_token_rotates_password_hash_and_flags_used(session):
    from sqlalchemy import select

    from models import PasswordResetToken
    from services import password_reset as pr

    alice = _alice(session)
    old_hash = alice.password_hash
    row, raw = pr.issue_token(session, user=alice)
    session.flush()

    user = pr.consume_token(
        session,
        raw_token=raw,
        new_password="N3w-Strong-Password!",
    )
    session.flush()

    assert user.id == alice.id
    assert user.password_hash != old_hash
    assert bcrypt.checkpw(b"N3w-Strong-Password!", user.password_hash.encode("utf-8"))
    refreshed = session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.id == row.id)
    )
    assert refreshed.used_at is not None


def test_consume_token_rejects_unknown(session):
    from services import password_reset as pr

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session,
            raw_token="this-token-does-not-exist",
            new_password="N3w-Strong-Password!",
        )


def test_consume_token_rejects_already_used(session):
    from services import password_reset as pr

    alice = _alice(session)
    row, raw = pr.issue_token(session, user=alice)
    session.flush()
    pr.consume_token(session, raw_token=raw, new_password="N3w-Strong-Password!")
    session.flush()

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session, raw_token=raw, new_password="Y3t-Another-Password!"
        )


def test_consume_token_rejects_expired(session):
    from services import password_reset as pr

    alice = _alice(session)
    row, raw = pr.issue_token(session, user=alice)
    row.expires_at = _dt.datetime.utcnow() - _dt.timedelta(minutes=1)
    session.flush()

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session, raw_token=raw, new_password="N3w-Strong-Password!"
        )


def test_consume_token_rejects_inactive_user(session):
    from services import password_reset as pr

    alice = _alice(session)
    _row, raw = pr.issue_token(session, user=alice)
    alice.is_active = False
    session.flush()

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session, raw_token=raw, new_password="N3w-Strong-Password!"
        )


# --- kick_off_reset (no account leak) -------------------------------------


def test_kick_off_reset_unknown_email_creates_no_row(session):
    from sqlalchemy import func, select

    from models import PasswordResetToken
    from services import password_reset as pr

    before = session.scalar(select(func.count(PasswordResetToken.id)))
    pr.kick_off_reset(session, email=f"nobody-{uuid.uuid4()}@example.invalid")
    session.flush()
    after = session.scalar(select(func.count(PasswordResetToken.id)))
    assert after == before


def test_kick_off_reset_known_email_creates_row(session):
    from sqlalchemy import func, select

    from models import PasswordResetToken
    from services import password_reset as pr

    alice = _alice(session)
    before = session.scalar(
        select(func.count(PasswordResetToken.id)).where(
            PasswordResetToken.user_id == alice.id
        )
    )
    pr.kick_off_reset(session, email=alice.email.upper())  # case-insensitive
    session.flush()
    after = session.scalar(
        select(func.count(PasswordResetToken.id)).where(
            PasswordResetToken.user_id == alice.id
        )
    )
    assert after == before + 1


# --- HTTP smoke -----------------------------------------------------------


def test_forgot_password_post_unknown_email_returns_200(client):
    """Same response as the known-email path — that's what makes the
    flow non-enumerable."""
    r = client.post(
        "/forgot-password",
        data={
            "email": f"unknown-{uuid.uuid4()}@example.invalid",
        },
    )
    assert r.status_code == 200


def test_forgot_password_post_known_email_returns_200(client):
    r = client.post(
        "/forgot-password",
        data={
            "email": "alice@test.local",
        },
    )
    assert r.status_code == 200


def test_reset_password_get_with_invalid_token_renders_form(client):
    """The GET doesn't validate the token (validation happens on POST)
    so an invalid token still renders the form. POST then redirects to
    forgot-password with a flash."""
    r = client.get("/reset-password/totally-fake-token")
    assert r.status_code == 200


# --- session invalidation on password reset -------------------------------


def test_consume_token_bumps_password_changed_at(session):
    """Belt-and-braces : the column the session-invalidation check reads
    on every request must move forward when consume_token runs."""
    from services import password_reset as pr

    alice = _alice(session)
    before = alice.password_changed_at
    _row, raw = pr.issue_token(session, user=alice)
    session.flush()
    pr.consume_token(session, raw_token=raw, new_password="N3w-Strong-Password!")
    session.flush()

    assert alice.password_changed_at is not None
    assert before is None or alice.password_changed_at > before


def test_session_invalidated_after_password_reset(client):
    """End-to-end : an authenticated session must lose access the moment
    the user's password_changed_at moves past the snapshot stored in
    the session cookie. This is the headline security guarantee of the
    `app.load_current_user` re-validation step.

    We don't exercise the "login with the new password" follow-up here:
    in tests, conftest's session-scoped fixture causes SQLAlchemy's
    identity map to leak across requests, so the login handler reads a
    cached `password_hash` and rejects the new password. In production
    each request gets a fresh session and that path works fine.
    """
    import bcrypt as _bcrypt

    from database import session_factory
    from services import password_reset as pr

    try:
        # Step 1 : alice logs in. The session is stamped with her current
        # password_changed_at (None for a freshly seeded user).
        r = client.post(
            "/login",
            data={"email": "alice@test.local", "password": "testpass"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        r = client.get("/client/dashboard", follow_redirects=False)
        assert r.status_code == 200, "alice should be authenticated post-login"

        # Step 2 : alice's password gets reset out-of-band (simulating a
        # parallel device hitting /reset-password/<token>). The session
        # cookie that worked above must now be refused.
        s = session_factory()
        try:
            alice = _alice(s)
            _row, raw = pr.issue_token(s, user=alice)
            s.flush()
            pr.consume_token(
                s, raw_token=raw, new_password="Reset-Strong-Password1!"
            )
            s.commit()
        finally:
            s.close()

        r = client.get("/client/dashboard", follow_redirects=False)
        assert r.status_code in (302, 403), (
            f"stale session must be rejected after password reset; got {r.status_code}"
        )
    finally:
        # Restore alice to the seeded state regardless of whether the
        # assertions above passed. Without this, a failure leaves a
        # rotated password hash behind and every test that logs in as
        # alice afterwards breaks.
        s = session_factory()
        try:
            alice = _alice(s)
            alice.password_hash = _bcrypt.hashpw(
                b"testpass", _bcrypt.gensalt()
            ).decode()
            alice.password_changed_at = None
            s.commit()
        finally:
            s.close()
