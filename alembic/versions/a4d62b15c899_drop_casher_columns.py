"""drop dietary_casher and casher_count columns

Revision ID: a4d62b15c899
Revises: f9c8e2b53741
Create Date: 2026-04-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a4d62b15c899"
down_revision: Union[str, Sequence[str], None] = "f9c8e2b53741"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("caterers", "dietary_casher")
    op.drop_column("quote_requests", "dietary_casher")
    op.drop_column("quote_requests", "casher_count")


def downgrade() -> None:
    op.add_column(
        "caterers",
        sa.Column("dietary_casher", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "quote_requests",
        sa.Column("dietary_casher", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "quote_requests",
        sa.Column("casher_count", sa.Integer(), nullable=True),
    )
