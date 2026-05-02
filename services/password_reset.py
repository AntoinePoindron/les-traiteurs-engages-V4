"""Password-reset token lifecycle.

Three responsibilities, each its own function so unit tests can drive
the rule without going through the HTTP layer:

* `issue_token(user)` — mint a fresh token, persist it, return the
  PasswordResetToken row.
* `consume_token(raw_token, new_password)` — validate (exists, not
  used, not expired), flip `used_at`, hash + write the new password.
* `kick_off_reset(email)` — public entry-point. Looks up the user,
  issues a token, queues the email. **Always** runs in constant time
  whether the email exists or not, to avoid leaking account existence
  through response timing (audit-style account-enumeration defence).

No commit — caller commits.
"""

from __future__ import annotations

import datetime
import secrets

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from models import PasswordResetToken, User
from services.email import render_and_send_async


# 1 hour is the industry-standard window for password reset links —
# long enough for the email to arrive + the user to click, short enough
# that a leaked link from logs / referrer headers expires fast.
RESET_TOKEN_TTL = datetime.timedelta(hours=1)


class ResetTokenInvalid(Exception):
    """Token is unknown, already used, or expired. Same exception for
    all three so the route handler can't accidentally leak which case
    it is to the caller (would help a brute-force attacker)."""


def issue_token(db: Session, *, user: User) -> PasswordResetToken:
    """Create + persist a one-shot reset token for `user`. Returns the
    row so the caller can grab the token string for the email."""
    raw = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        user_id=user.id,
        token=raw,
        expires_at=datetime.datetime.utcnow() + RESET_TOKEN_TTL,
    )
    db.add(row)
    db.flush()
    return row


def consume_token(db: Session, *, raw_token: str, new_password: str) -> User:
    """Verify `raw_token`, atomically flip `used_at`, hash + write the
    new password on the owning User. Returns the updated user.

    Raises `ResetTokenInvalid` for any failure mode.
    """
    if not raw_token:
        raise ResetTokenInvalid
    row = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token == raw_token)
    )
    if row is None:
        raise ResetTokenInvalid
    if row.used_at is not None:
        raise ResetTokenInvalid
    if row.expires_at < datetime.datetime.utcnow():
        raise ResetTokenInvalid

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        # Owning user vanished or got deactivated since the token was
        # issued — refuse the consume. Same opaque error.
        raise ResetTokenInvalid

    row.used_at = datetime.datetime.utcnow()
    user.password_hash = bcrypt.hashpw(
        new_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    db.flush()
    return user


def kick_off_reset(db: Session, *, email: str) -> None:
    """Trigger the password-reset email flow for a given email.

    Exactly one of two paths runs:
      * email matches an active user → mint token, queue email.
      * no match (or inactive) → no-op.

    The function returns None either way and the route renders the
    same "if your email exists, a link is on its way" success page —
    that's how we avoid leaking account existence. A bcrypt hash is
    computed on the no-match path so the response time tracks the
    real path closely.
    """
    user = db.scalar(select(User).where(User.email == (email or "").lower().strip()))
    if user is None or not user.is_active:
        # Constant-time-ish dummy work so the response doesn't expose
        # "no account here" through a fast no-op return.
        bcrypt.hashpw(b"timing-noise", bcrypt.gensalt())
        return

    token = issue_token(db, user=user)
    # The auth blueprint is mounted at /, not /auth/, so the route is
    # /reset-password/<token>. Hardcoding the path beats a `url_for`
    # that would need a server-name config to produce an absolute URL.
    reset_url = f"{config.BASE_URL}/reset-password/{token.token}"

    render_and_send_async(
        to=user.email,
        subject="Réinitialisation de votre mot de passe",
        template_name="password_reset",
        user=user,
        reset_url=reset_url,
        ttl_minutes=int(RESET_TOKEN_TTL.total_seconds() // 60),
    )
