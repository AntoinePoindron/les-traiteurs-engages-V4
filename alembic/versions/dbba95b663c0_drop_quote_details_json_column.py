"""drop Quote.details JSON column

Revision ID: dbba95b663c0
Revises: 1e6220186827
Create Date: 2026-04-24

The column was a lossy float cache of values that already live as proper
Numeric columns on Quote. After PR 12 moved `lines` into `quote_lines`,
nothing canonical lived in `details` anymore — half-orphan with duplicated
truth. Templates and stripe_service recompute totals on demand.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "dbba95b663c0"
down_revision: Union[str, Sequence[str], None] = "1e6220186827"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("quotes", "details")


def downgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("details", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )
