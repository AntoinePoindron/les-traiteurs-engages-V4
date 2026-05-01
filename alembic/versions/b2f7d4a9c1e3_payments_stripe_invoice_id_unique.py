"""payments.stripe_invoice_id UNIQUE

Revision ID: b2f7d4a9c1e3
Revises: a1e3c9f2d7b8
Create Date: 2026-04-24

One Stripe invoice should map to exactly one Payment row. Without a
UNIQUE constraint, two concurrent `POST /caterer/orders/<id>/deliver`
requests can both pass the `status==confirmed` gate and insert
duplicate Payments; the webhook handler then updates only one of them.
Audit finding #6 (2026-04-24).
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b2f7d4a9c1e3"
down_revision: Union[str, Sequence[str], None] = "a1e3c9f2d7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_payments_stripe_invoice_id",
        "payments",
        ["stripe_invoice_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_payments_stripe_invoice_id", "payments", type_="unique")
