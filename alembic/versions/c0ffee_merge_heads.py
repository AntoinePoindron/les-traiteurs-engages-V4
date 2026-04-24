"""merge dev branches: stripe-audit + drop-Quote.details

Revision ID: c0ffee0fea7
Revises: b2f7d4a9c1e3, dbba95b663c0
Create Date: 2026-04-24
"""
from typing import Sequence, Union

revision: str = "c0ffee0fea7"
down_revision: Union[str, Sequence[str], None] = ("b2f7d4a9c1e3", "dbba95b663c0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
