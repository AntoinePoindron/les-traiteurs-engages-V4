"""add_setup_time_details_and_nappes_livraison_flags

Revision ID: e5b1c2a4d8f9
Revises: d2e3f4a5b6c7
Create Date: 2026-05-03 10:10:00.000000

Step 6 of the wizard ("Services complémentaires") was reorganised in
3 groups (Personnel / Matériel / Installation et mise en place) and
two prestations were promoted from ghost-checkboxes (visible in the
template, ignored by the form) to real persisted fields:
  - `wants_nappes`      — BOOLEAN
  - `wants_livraison`   — BOOLEAN

Same migration also adds the install/setup details captured when the
client ticks "Installation / mise en place" :
  - `service_setup_time`    — TIME (UI-required when wants_setup is True,
                              nullable in DB to keep legacy rows valid)
  - `service_setup_details` — TEXT (optional précisions)

Stacks on the local merge migration `d2e3f4a5b6c7` so it lives on the
same chain as caterer_reviews / password_reset / event_times.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5b1c2a4d8f9"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote_requests",
        sa.Column(
            "wants_nappes",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "quote_requests",
        sa.Column(
            "wants_livraison",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "quote_requests",
        sa.Column("service_setup_time", sa.Time(), nullable=True),
    )
    op.add_column(
        "quote_requests",
        sa.Column("service_setup_details", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quote_requests", "service_setup_details")
    op.drop_column("quote_requests", "service_setup_time")
    op.drop_column("quote_requests", "wants_livraison")
    op.drop_column("quote_requests", "wants_nappes")
