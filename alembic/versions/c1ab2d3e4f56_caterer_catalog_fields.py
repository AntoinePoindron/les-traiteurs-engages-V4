"""add caterer catalog fields (service_offerings, price range, advance days)

Revision ID: c1ab2d3e4f56
Revises: a7b3c1d2e4f5
Create Date: 2026-04-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c1ab2d3e4f56"
down_revision: Union[str, Sequence[str], None] = "a7b3c1d2e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # service_offerings: list of slug strings consumed by the catalog
    # search filter ("Type de prestation"). See models.SERVICE_OFFERING_LABELS
    # for the canonical (slug, label) pairs. JSON keeps it flexible and
    # avoids a join table for a list of < 10 fixed-but-evolving choices.
    op.add_column(
        "caterers",
        sa.Column("service_offerings", sa.JSON(), nullable=True),
    )
    # price_per_person_{min,max}: decimal price range advertised by the
    # caterer. Used by the "Budget / personne" filter — a caterer matches
    # a band when its [min, max] range overlaps the band bounds.
    op.add_column(
        "caterers",
        sa.Column("price_per_person_min", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "caterers",
        sa.Column("price_per_person_max", sa.Numeric(10, 2), nullable=True),
    )
    # min_advance_days: minimum lead time the caterer requires; surfaced
    # under each card on the catalog ("À commander N jours à l'avance").
    op.add_column(
        "caterers",
        sa.Column("min_advance_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("caterers", "min_advance_days")
    op.drop_column("caterers", "price_per_person_max")
    op.drop_column("caterers", "price_per_person_min")
    op.drop_column("caterers", "service_offerings")
