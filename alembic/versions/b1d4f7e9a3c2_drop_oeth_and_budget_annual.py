"""drop oeth_eligible and budget_annual from companies

Revision ID: b1d4f7e9a3c2
Revises: e5b1c2a4d8f9
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b1d4f7e9a3c2"
down_revision: Union[str, Sequence[str], None] = "e5b1c2a4d8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("companies", "budget_annual")
    op.drop_column("companies", "oeth_eligible")


def downgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "oeth_eligible", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "companies",
        sa.Column("budget_annual", sa.Numeric(precision=12, scale=2), nullable=True),
    )
