"""add invite_token to company_employees

Stores the single-use signup token an admin generates for a collaborator
via /client/team. The collaborator then redeems it on /signup/invite/<token>
to attach to the company without going through the SIRET pending-approval
flow. Token expires 7 days after invited_at; cleared on redemption.

Revision ID: b3e84f217a5d
Revises: a4d62b15c899
Create Date: 2026-05-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3e84f217a5d"
down_revision: Union[str, Sequence[str], None] = "a4d62b15c899"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "company_employees",
        sa.Column("invite_token", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_company_employees_invite_token",
        "company_employees",
        ["invite_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_employees_invite_token", table_name="company_employees"
    )
    op.drop_column("company_employees", "invite_token")
