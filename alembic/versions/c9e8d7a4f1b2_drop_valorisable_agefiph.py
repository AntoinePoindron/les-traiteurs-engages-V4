"""drop valorisable_agefiph from quotes and invoices

Revision ID: c9e8d7a4f1b2
Revises: b1d4f7e9a3c2
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c9e8d7a4f1b2"
down_revision: Union[str, Sequence[str], None] = "b1d4f7e9a3c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("quotes", "valorisable_agefiph")
    op.drop_column("invoices", "valorisable_agefiph")


def downgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column(
            "valorisable_agefiph", sa.Numeric(precision=12, scale=2), nullable=True
        ),
    )
    op.add_column(
        "invoices",
        sa.Column(
            "valorisable_agefiph", sa.Numeric(precision=12, scale=2), nullable=True
        ),
    )
