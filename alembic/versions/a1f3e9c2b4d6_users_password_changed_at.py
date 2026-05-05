"""add password_changed_at to users

Tracks the moment a user's `password_hash` was last rotated. Stored on
the session as `pwd_changed_at` and compared on every request — sessions
issued before the most recent rotation are silently invalidated. Closes
the "session keeps working after password reset" gap.

Backward-compat : the column is nullable. Existing users + existing
sessions read NULL/None and compare equal, so no forced logout on
deploy. The first password reset bumps the column and invalidates any
older sessions for that user.

Revision ID: a1f3e9c2b4d6
Revises: a92e1c5d4f8b
Create Date: 2026-05-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1f3e9c2b4d6"
down_revision: Union[str, Sequence[str], None] = "a92e1c5d4f8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
