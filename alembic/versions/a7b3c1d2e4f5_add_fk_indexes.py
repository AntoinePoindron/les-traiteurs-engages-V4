"""add indexes on frequently queried foreign keys

Revision ID: a7b3c1d2e4f5
Revises: f3a7b2c1d9e4
Create Date: 2026-04-30
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a7b3c1d2e4f5"
down_revision: Union[str, Sequence[str], None] = "f3a7b2c1d9e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) pairs that need indexes.
_INDEXES = [
    ("users", "company_id"),
    ("users", "caterer_id"),
    ("company_services", "company_id"),
    ("company_employees", "company_id"),
    ("company_employees", "service_id"),
    ("quote_requests", "company_id"),
    ("quote_requests", "company_service_id"),
    ("quote_request_caterers", "quote_request_id"),
    ("quote_request_caterers", "caterer_id"),
    ("quotes", "quote_request_id"),
    ("quotes", "caterer_id"),
    ("invoices", "order_id"),
    ("invoices", "caterer_id"),
    ("payments", "order_id"),
    ("payments", "caterer_id"),
    ("notifications", "user_id"),
    ("messages", "sender_id"),
    ("messages", "recipient_id"),
]


def upgrade() -> None:
    for table, column in _INDEXES:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table, column in reversed(_INDEXES):
        op.drop_index(f"ix_{table}_{column}", table_name=table)
