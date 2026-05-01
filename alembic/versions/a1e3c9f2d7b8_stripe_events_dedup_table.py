"""stripe_events dedup table

Revision ID: a1e3c9f2d7b8
Revises: 1e6220186827
Create Date: 2026-04-24

Adds a table keyed on Stripe's event.id to dedupe webhook deliveries.
Addresses audit finding #3: Stripe can re-deliver events and the signature
check tolerates a 300s window in which an attacker could replay a captured
body+signature. Inserting event.id inside the handler gives us an atomic
"already processed" signal via UNIQUE violation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1e3c9f2d7b8"
down_revision: Union[str, Sequence[str], None] = "1e6220186827"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("stripe_events")
