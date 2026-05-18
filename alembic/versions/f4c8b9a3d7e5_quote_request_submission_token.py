"""Add idempotent `submission_token` column on quote_requests.

Symptom this fixes: a client who pressed "back" after submitting the
wizard and re-validated ended up creating a second QuoteRequest. The
wizard is now expected to ship a UUID hidden field (`form_token`)
that the POST handler persists here; the UNIQUE constraint catches
the second insert and redirects to the original detail page instead
of duplicating.

The column is nullable so existing rows aren't disturbed.

Revision ID: f4c8b9a3d7e5
Revises: a6f3b8e2d4c7
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f4c8b9a3d7e5"
down_revision: Union[str, Sequence[str], None] = "a6f3b8e2d4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote_requests",
        sa.Column("submission_token", sa.String(length=36), nullable=True),
    )
    op.create_unique_constraint(
        "uq_quote_requests_submission_token",
        "quote_requests",
        ["submission_token"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_quote_requests_submission_token", "quote_requests", type_="unique"
    )
    op.drop_column("quote_requests", "submission_token")
