"""terms_versions table + user acceptance columns + seed v1.

Adds the plumbing for CGS (Conditions Générales de Services) acceptance
at signup:

* `terms_versions` registers the metadata of each CGS version (the body
  lives in a Jinja template — see `template_name`). Seeded with `v1`
  effective 2026-04-09, rendered by `templates/legal/cgs_v1.html`.
* `users` gains `terms_accepted_version_id` (FK → terms_versions) and
  `terms_accepted_at`, both nullable so existing rows aren't disturbed
  (staging-only platform, no real users yet — see PR for the call).

Revision ID: d28a1b4e5f3c
Revises: e7c8a2f4b6d1
Create Date: 2026-05-13
"""

import datetime
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d28a1b4e5f3c"
# Re-parented onto e7c8a2f4b6d1 (PR #59 drinks column) — itself a child
# of f4c8b9a3d7e5 — so this PR merges cleanly after #59 lands without
# creating a fresh two-headed graph. Originally branched from
# a6f3b8e2d4c7 like every PR in the v0.4 batch.
down_revision: Union[str, Sequence[str], None] = "e7c8a2f4b6d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_V1_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def upgrade() -> None:
    op.create_table(
        "terms_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("effective_at", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.add_column(
        "users",
        sa.Column("terms_accepted_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(), nullable=True),
    )
    op.create_foreign_key(
        "fk_users_terms_accepted_version_id",
        "users",
        "terms_versions",
        ["terms_accepted_version_id"],
        ["id"],
    )

    # Seed v1. The exact id is fixed so subsequent migrations (or test
    # fixtures) can reference it without a slug lookup.
    op.execute(
        sa.text(
            "INSERT INTO terms_versions "
            "(id, slug, title, template_name, effective_at) "
            "VALUES (:id, :slug, :title, :template_name, :effective_at)"
        ).bindparams(
            id=str(_V1_ID),
            slug="v1",
            title="CGS v1 — Avril 2026",
            template_name="legal/cgs_v1.html",
            effective_at=datetime.date(2026, 4, 9),
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_users_terms_accepted_version_id", "users", type_="foreignkey"
    )
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_accepted_version_id")
    op.drop_table("terms_versions")
