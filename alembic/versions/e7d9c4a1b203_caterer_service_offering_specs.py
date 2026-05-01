"""add service_offering_specs JSON to caterers

Revision ID: e7d9c4a1b203
Revises: f3a7b2c1d9e4
Create Date: 2026-04-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e7d9c4a1b203"
down_revision: Union[str, Sequence[str], None] = "c1ab2d3e4f56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-service-offering pricing/capacity specs. Shape is
    #   {slug: {capacity_min, capacity_max, price_per_person_min,
    #           total_min, min_advance_days}}
    # where slug is one of SERVICE_OFFERING_LABELS. Validated server-side
    # in the profile handler so unknown slugs / non-numeric values can't
    # be persisted from a tampered request.
    op.add_column(
        "caterers",
        sa.Column("service_offering_specs", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("caterers", "service_offering_specs")
