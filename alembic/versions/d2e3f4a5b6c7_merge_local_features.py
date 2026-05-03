"""merge local feature branches: caterer_reviews + password_reset + event_times

Revision ID: d2e3f4a5b6c7
Revises: 11a3c9fbf7ee, a92e1c5d4f8b, ff23d8dac807
Create Date: 2026-05-03

Empty merge node — used to collapse the three independent migrations
landed by feat/caterer-reviews, feat/email-p0-core and modifs-ui-2 into a
single linear head on the local integration branch.
"""

from typing import Sequence, Union

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = (
    "11a3c9fbf7ee",
    "a92e1c5d4f8b",
    "ff23d8dac807",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
