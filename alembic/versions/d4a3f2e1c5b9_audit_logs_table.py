"""audit_logs table

Revision ID: d4a3f2e1c5b9
Revises: c0ffee0fea7
Create Date: 2026-04-28

Append-only journal of sensitive admin actions (caterer validation,
quote-request qualification, etc.). Written by services.audit.log_admin_action.
Application code never updates or deletes rows in this table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4a3f2e1c5b9"
down_revision: Union[str, Sequence[str], None] = "c0ffee0fea7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_target_id", "audit_logs", ["target_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_target_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_table("audit_logs")
