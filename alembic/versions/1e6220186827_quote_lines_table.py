"""quote_lines table + backfill from Quote.details.lines

Revision ID: 1e6220186827
Revises: 8b9c44e016c3
Create Date: 2026-04-24 14:18:23
"""
import uuid
from decimal import Decimal
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1e6220186827"
down_revision: Union[str, Sequence[str], None] = "8b9c44e016c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quote_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price_ht", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tva_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_quote_lines_quote_id", "quote_id"),
    )

    # Backfill: each existing Quote with details.lines becomes quote_lines rows.
    bind = op.get_bind()
    quotes = bind.execute(sa.text("SELECT id, details FROM quotes WHERE details IS NOT NULL")).fetchall()
    rows = []
    for qid, details in quotes:
        if not isinstance(details, dict):
            continue
        for i, line in enumerate(details.get("lines") or []):
            rows.append({
                "id": uuid.uuid4(),
                "quote_id": qid,
                "position": i,
                "section": str(line.get("section") or "principal")[:50],
                "description": line.get("description"),
                "quantity": Decimal(str(line.get("quantity", 0))),
                "unit_price_ht": Decimal(str(line.get("unit_price_ht", 0))),
                "tva_rate": Decimal(str(line.get("tva_rate", 10))),
            })
    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO quote_lines (id, quote_id, position, section, description,"
                " quantity, unit_price_ht, tva_rate) VALUES"
                " (:id, :quote_id, :position, :section, :description,"
                " :quantity, :unit_price_ht, :tva_rate)"
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_table("quote_lines")
