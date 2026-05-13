"""Add `drinks` JSON column to quote_requests.

The wizard step 5 (Boissons) exposes 7 checkboxes — eau plate, eau gazeuse,
soft, bières, vins, champagne, boissons chaudes — that until now were
posted to the form but stored nowhere. Only the legacy `drinks_alcohol`
boolean (no longer exposed by the wizard) was persisted, which is why
the detail pages always read "Sans alcool".

This migration adds a nullable JSON column to hold the list of selected
slugs. Backfill is intentionally left out: existing rows keep `drinks =
NULL` and the templates degrade gracefully (no "Boissons" section). The
post-deploy expectation is that anyone who needs the data re-saves the
request from the wizard.

Revision ID: e7c8a2f4b6d1
Revises: a6f3b8e2d4c7
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7c8a2f4b6d1"
down_revision: Union[str, Sequence[str], None] = "a6f3b8e2d4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote_requests",
        sa.Column("drinks", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quote_requests", "drinks")
