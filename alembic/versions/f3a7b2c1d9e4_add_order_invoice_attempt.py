"""add order invoice_attempt column

Revision ID: f3a7b2c1d9e4
Revises: d4a3f2e1c5b9
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f3a7b2c1d9e4"
down_revision: Union[str, Sequence[str], None] = "d4a3f2e1c5b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("invoice_attempt", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("orders", "invoice_attempt")
