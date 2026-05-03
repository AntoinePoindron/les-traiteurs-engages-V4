"""add_caterer_reviews

Revision ID: 11a3c9fbf7ee
Revises: a4d62b15c899
Create Date: 2026-05-02 11:26:22.980689

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "11a3c9fbf7ee"
down_revision: Union[str, Sequence[str], None] = "a4d62b15c899"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the `caterer_reviews` table.

    Constraints :
      * UNIQUE on order_id — one review per paid order.
      * CHECK rating BETWEEN 1 AND 5 — DB-level guard so even direct
        SQL writes can't poison the average.
    """
    op.create_table(
        "caterer_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "caterer_id",
            sa.Uuid(),
            sa.ForeignKey("caterers.id"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 5", name="caterer_reviews_rating_range"
        ),
        sa.UniqueConstraint("order_id", name="caterer_reviews_order_unique"),
    )
    op.create_index(
        "ix_caterer_reviews_caterer_id",
        "caterer_reviews",
        ["caterer_id"],
    )
    op.create_index(
        "ix_caterer_reviews_reviewer_user_id",
        "caterer_reviews",
        ["reviewer_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_caterer_reviews_reviewer_user_id", table_name="caterer_reviews")
    op.drop_index("ix_caterer_reviews_caterer_id", table_name="caterer_reviews")
    op.drop_table("caterer_reviews")
