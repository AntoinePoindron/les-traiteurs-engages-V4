"""commission_invoice_number sequence + Decimal type-hint cleanup

Revision ID: 8b9c44e016c3
Revises: 233107e88e63
Create Date: 2026-04-24 13:37:19

Closes the previous max(invoice_number)+1 race condition by delegating
numbering to a Postgres SEQUENCE. Required for French fiscal compliance
(strictly sequential, no duplicates, no gaps in concurrent execution).

Also makes `invoices.tva_rate` nullable so we can store NULL when a
quote has zero HT (rather than fabricating a fake 10% rate).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b9c44e016c3"
down_revision: Union[str, Sequence[str], None] = "233107e88e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEQ_NAME = "commission_invoice_number_seq"


def upgrade() -> None:
    # 1. Create the sequence, seeded above any existing invoice_number so
    #    it can never collide with rows already written by the old
    #    max(...)+1 path.
    op.execute(f"CREATE SEQUENCE IF NOT EXISTS {SEQ_NAME}")
    op.execute(
        f"SELECT setval('{SEQ_NAME}', "
        f"COALESCE((SELECT MAX(invoice_number) FROM commission_invoices), 0) + 1, "
        f"false)"
    )

    # 2. Default new rows to nextval(seq) — the application no longer assigns
    #    invoice_number explicitly.
    op.execute(
        f"ALTER TABLE commission_invoices "
        f"ALTER COLUMN invoice_number SET DEFAULT nextval('{SEQ_NAME}')"
    )

    # 3. Enforce uniqueness at the DB level so any future bug that tries to
    #    write a duplicate gets rejected immediately.
    op.create_unique_constraint(
        "commission_invoices_invoice_number_key",
        "commission_invoices",
        ["invoice_number"],
    )

    # 4. tva_rate becomes nullable on Invoice — see service-layer change for
    #    the rationale (no fabricated rate when there is nothing to compute).
    op.alter_column(
        "invoices",
        "tva_rate",
        existing_type=sa.NUMERIC(precision=5, scale=4),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "invoices",
        "tva_rate",
        existing_type=sa.NUMERIC(precision=5, scale=4),
        nullable=False,
    )
    op.drop_constraint(
        "commission_invoices_invoice_number_key",
        "commission_invoices",
        type_="unique",
    )
    op.execute("ALTER TABLE commission_invoices ALTER COLUMN invoice_number DROP DEFAULT")
    op.execute(f"DROP SEQUENCE IF EXISTS {SEQ_NAME}")
