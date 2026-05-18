"""Hash password-reset and employee-invite tokens at rest.

Rationale (audit 2026-05-18) : both tokens were stored verbatim, so a
DB compromise (backup leak, malicious operator, future SQLi) would let
the attacker reuse every live link. Lookup is by exact value either
way, so storing the SHA-256 digest costs nothing — services hash the
incoming token before the WHERE clause.

Live tokens already in the wild keep working : the migration rewrites
the column in place to the digest, and the application's consume path
hashes the URL token before the lookup. Users with an unopened reset
email still find their link valid; users with an outstanding invite
URL still complete signup.

Revision ID: c4d2e8f7a1b9
Revises: d28a1b4e5f3c
Create Date: 2026-05-18
"""

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4d2e8f7a1b9"
down_revision: Union[str, Sequence[str], None] = "d28a1b4e5f3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()

    # Password reset: hash only unused, non-expired rows. Used / expired
    # rows are dead weight; hashing them would still work but it's wasted
    # cycles and clutters the diff for the operator running this.
    pending_resets = bind.execute(
        sa.text(
            "SELECT id, token FROM password_reset_tokens "
            "WHERE used_at IS NULL AND expires_at > NOW()"
        )
    ).fetchall()
    for row_id, raw in pending_resets:
        # 64 chars = SHA-256 hex. The column is String(64) already, so no
        # ALTER. The raw token coming in is `token_urlsafe(32)` (43 chars)
        # or — defensively — already a digest if this migration was
        # re-run; the second case is a no-op via `LENGTH(token) = 64`.
        if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw):
            continue
        bind.execute(
            sa.text(
                "UPDATE password_reset_tokens SET token = :digest WHERE id = :id"
            ),
            {"digest": _sha256_hex(raw), "id": row_id},
        )

    # Employee invites: hash every live one (user_id IS NULL, token IS
    # NOT NULL). Once redeemed, invite_token is already NULLed by the
    # signup handler, so they're out of scope.
    pending_invites = bind.execute(
        sa.text(
            "SELECT id, invite_token FROM company_employees "
            "WHERE invite_token IS NOT NULL AND user_id IS NULL"
        )
    ).fetchall()
    for row_id, raw in pending_invites:
        if len(raw) == 64 and all(c in "0123456789abcdef" for c in raw):
            continue
        bind.execute(
            sa.text(
                "UPDATE company_employees SET invite_token = :digest WHERE id = :id"
            ),
            {"digest": _sha256_hex(raw), "id": row_id},
        )


def downgrade() -> None:
    # Irreversible : SHA-256 is one-way. A downgrade would have to drop
    # every live token (turning them into 404s on use) which is exactly
    # what we want NOT to do silently. Operators who need to revert
    # should run the downgrade explicitly knowing every live link breaks.
    op.execute(
        "UPDATE password_reset_tokens SET used_at = NOW() "
        "WHERE used_at IS NULL AND expires_at > NOW()"
    )
    op.execute(
        "UPDATE company_employees SET invite_token = NULL, invited_at = NULL "
        "WHERE invite_token IS NOT NULL AND user_id IS NULL"
    )
