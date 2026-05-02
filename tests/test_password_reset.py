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
    row = pr.issue_token(session, user=alice)
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


def test_issue_token_returns_unique_strings(session):
    from services import password_reset as pr

    alice = _alice(session)
    a = pr.issue_token(session, user=alice).token
    b = pr.issue_token(session, user=alice).token
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
    row = pr.issue_token(session, user=alice)
    session.flush()

    user = pr.consume_token(
        session,
        raw_token=row.token,
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
    row = pr.issue_token(session, user=alice)
    session.flush()
    pr.consume_token(session, raw_token=row.token, new_password="N3w-Strong-Password!")
    session.flush()

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session, raw_token=row.token, new_password="Y3t-Another-Password!"
        )


def test_consume_token_rejects_expired(session):
    from services import password_reset as pr

    alice = _alice(session)
    row = pr.issue_token(session, user=alice)
    row.expires_at = _dt.datetime.utcnow() - _dt.timedelta(minutes=1)
    session.flush()

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session, raw_token=row.token, new_password="N3w-Strong-Password!"
        )


def test_consume_token_rejects_inactive_user(session):
    from services import password_reset as pr

    alice = _alice(session)
    row = pr.issue_token(session, user=alice)
    alice.is_active = False
    session.flush()

    with pytest.raises(pr.ResetTokenInvalid):
        pr.consume_token(
            session, raw_token=row.token, new_password="N3w-Strong-Password!"
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
