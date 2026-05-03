"""add_event_start_end_time_to_quote_requests

Revision ID: ff23d8dac807
Revises: a4d62b15c899
Create Date: 2026-05-03 08:52:41.374359

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ff23d8dac807"
down_revision: Union[str, Sequence[str], None] = "a4d62b15c899"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add event_start_time + event_end_time on quote_requests.

    Both nullable — pre-existing rows have no times. The form requires
    them for new submissions but legacy rows are read-only as far as
    times are concerned.
    """
    op.add_column(
        "quote_requests",
        sa.Column("event_start_time", sa.Time(), nullable=True),
    )
    op.add_column(
        "quote_requests",
        sa.Column("event_end_time", sa.Time(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quote_requests", "event_end_time")
    op.drop_column("quote_requests", "event_start_time")
