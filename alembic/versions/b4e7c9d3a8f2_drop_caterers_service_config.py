"""drop caterers.service_config — superseded by caterers.service_offerings.

The previous migration (a6f3b8e2d4c7) aligned the keys of
`caterers.service_config` and the values of `caterers.service_offerings`
on the same six prestation slugs. They've held duplicate information
ever since: a list of slugs vs. a dict of {slug: bool}.

This migration drops `service_config`. Application code now reads
`service_offerings` (a JSON list) for matching, search filtering, and
catalog display.

The downgrade re-adds the column and back-fills it from
`service_offerings` so the legacy code path keeps working if we roll
back.

Revision ID: b4e7c9d3a8f2
Revises: a6f3b8e2d4c7
Create Date: 2026-05-12
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import bindparam, text


revision: str = "b4e7c9d3a8f2"
down_revision: Union[str, Sequence[str], None] = "a6f3b8e2d4c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirror MEAL_TYPE_LABELS slugs — keep in sync with models.py if either
# list ever changes (this migration is intentionally self-contained and
# does NOT import application code to stay replay-safe).
_OFFERING_SLUGS = (
    "petit_dejeuner",
    "pause_gourmande",
    "plateaux_repas",
    "cocktail_dinatoire",
    "cocktail_dejeunatoire",
    "aperitif",
)


def upgrade() -> None:
    op.drop_column("caterers", "service_config")


def downgrade() -> None:
    op.add_column("caterers", sa.Column("service_config", sa.JSON(), nullable=True))

    # Back-fill the legacy dict from the still-current service_offerings
    # so matching keeps working under the old code path.
    conn = op.get_bind()
    rows = conn.execute(
        text(
            "SELECT id, service_offerings FROM caterers "
            "WHERE service_offerings IS NOT NULL"
        )
    ).fetchall()
    update_stmt = text(
        "UPDATE caterers SET service_config = CAST(:cfg AS JSON) WHERE id = :id"
    ).bindparams(bindparam("cfg"), bindparam("id"))

    for row in rows:
        offerings = row.service_offerings
        if not isinstance(offerings, list):
            continue
        cfg = {slug: (slug in offerings) for slug in _OFFERING_SLUGS}
        conn.execute(update_stmt, {"cfg": json.dumps(cfg), "id": row.id})
