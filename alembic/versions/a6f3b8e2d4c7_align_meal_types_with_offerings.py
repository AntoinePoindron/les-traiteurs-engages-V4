"""align quote_requests.meal_type and caterers.service_config with the
six service offering slugs published on caterer profiles.

Before this migration:
  - quote_requests.meal_type holds one of
    {dejeuner, diner, cocktail, petit_dejeuner, autre}
  - caterers.service_config is a JSON dict with the same five boolean keys.

After:
  - meal_type holds one of the six SERVICE_OFFERING_LABELS slugs
    {petit_dejeuner, pause_gourmande, plateaux_repas, cocktail_dinatoire,
     cocktail_dejeunatoire, aperitif}, or NULL.
  - service_config holds a JSON dict keyed on those six slugs.

Mapping for quote_requests.meal_type (validated with the user):
  petit_dejeuner -> petit_dejeuner  (unchanged)
  dejeuner       -> plateaux_repas
  diner          -> cocktail_dinatoire
  cocktail       -> cocktail_dinatoire
  autre          -> NULL  (no natural slug; let the client re-pick on edit)

Mapping for caterers.service_config keys (same intent, OR'd to preserve
"the caterer offers something in that family" semantics — e.g. an old
config with `dejeuner=true` becomes `plateaux_repas=true` after migrate):
  petit_dejeuner   -> petit_dejeuner
  dejeuner         -> plateaux_repas
  diner            -> cocktail_dinatoire
  cocktail         -> cocktail_dinatoire (OR'd with diner above)
  autre            -> plateaux_repas (best-effort default; OR'd as well)

Revision ID: a6f3b8e2d4c7
Revises: c9e8d7a4f1b2
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import bindparam, text


revision: str = "a6f3b8e2d4c7"
down_revision: Union[str, Sequence[str], None] = "c9e8d7a4f1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- quote_requests.meal_type: legacy -> new slug ---
_QR_FORWARD = {
    "dejeuner": "plateaux_repas",
    "diner": "cocktail_dinatoire",
    "cocktail": "cocktail_dinatoire",
    # `autre` becomes NULL — handled separately so the SQL stays readable.
}

# --- caterers.service_config: legacy key -> new key ---
# Multiple legacy keys can collapse into the same new key; the loop below
# OR's the booleans so no signal is lost.
_SC_FORWARD = {
    "petit_dejeuner": "petit_dejeuner",
    "dejeuner": "plateaux_repas",
    "diner": "cocktail_dinatoire",
    "cocktail": "cocktail_dinatoire",
    "autre": "plateaux_repas",
}

# Canonical set of keys the post-migration ServiceConfig accepts.
_NEW_SC_KEYS = (
    "petit_dejeuner",
    "pause_gourmande",
    "plateaux_repas",
    "cocktail_dinatoire",
    "cocktail_dejeunatoire",
    "aperitif",
)


def _remap_service_config(legacy: dict | None) -> dict | None:
    """Convert a legacy service_config dict to the new key set.

    OR-merges the value when several legacy keys map to the same new key.
    Unknown keys are silently dropped; values that aren't bools are coerced
    via `bool()` so legacy junk doesn't poison the new schema.
    """
    if not isinstance(legacy, dict):
        return None
    out = {k: False for k in _NEW_SC_KEYS}
    for legacy_key, val in legacy.items():
        new_key = _SC_FORWARD.get(legacy_key)
        if new_key is None:
            continue
        out[new_key] = bool(out[new_key] or val)
    return out


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Remap quote_requests.meal_type values in-place.
    for legacy, new in _QR_FORWARD.items():
        conn.execute(
            text("UPDATE quote_requests SET meal_type = :new WHERE meal_type = :legacy"),
            {"new": new, "legacy": legacy},
        )
    conn.execute(
        text("UPDATE quote_requests SET meal_type = NULL WHERE meal_type = 'autre'")
    )

    # 2. Remap caterers.service_config row-by-row (JSON column, no SQL trick).
    #    Python is fine here — caterer count is in the low thousands at most.
    rows = conn.execute(
        text("SELECT id, service_config FROM caterers WHERE service_config IS NOT NULL")
    ).fetchall()
    update_stmt = text(
        "UPDATE caterers SET service_config = CAST(:cfg AS JSON) WHERE id = :id"
    ).bindparams(bindparam("cfg"), bindparam("id"))
    import json

    for row in rows:
        new_cfg = _remap_service_config(row.service_config)
        if new_cfg is None:
            continue
        conn.execute(update_stmt, {"cfg": json.dumps(new_cfg), "id": row.id})


def downgrade() -> None:
    # No clean reverse mapping exists — `plateaux_repas` could come from
    # either `dejeuner` or `autre`, etc. The downgrade widens
    # `meal_type` back to the legacy set with a best-effort inverse and
    # drops the new-only values to NULL so the column re-fits in the
    # legacy enum.
    conn = op.get_bind()
    reverse = {
        "plateaux_repas": "dejeuner",
        "cocktail_dinatoire": "diner",
        "cocktail_dejeunatoire": "cocktail",
        "aperitif": "cocktail",
        "pause_gourmande": "petit_dejeuner",
        # petit_dejeuner stays petit_dejeuner.
    }
    for new, legacy in reverse.items():
        conn.execute(
            text("UPDATE quote_requests SET meal_type = :legacy WHERE meal_type = :new"),
            {"legacy": legacy, "new": new},
        )

    rows = conn.execute(
        text("SELECT id, service_config FROM caterers WHERE service_config IS NOT NULL")
    ).fetchall()
    import json

    update_stmt = text(
        "UPDATE caterers SET service_config = CAST(:cfg AS JSON) WHERE id = :id"
    ).bindparams(bindparam("cfg"), bindparam("id"))
    legacy_keys = ("petit_dejeuner", "dejeuner", "diner", "cocktail", "autre")
    inverse_key = {
        "petit_dejeuner": "petit_dejeuner",
        "pause_gourmande": "petit_dejeuner",
        "plateaux_repas": "dejeuner",
        "cocktail_dinatoire": "diner",
        "cocktail_dejeunatoire": "cocktail",
        "aperitif": "cocktail",
    }
    for row in rows:
        cfg = row.service_config or {}
        if not isinstance(cfg, dict):
            continue
        out = {k: False for k in legacy_keys}
        for k, v in cfg.items():
            lk = inverse_key.get(k)
            if lk is None:
                continue
            out[lk] = bool(out[lk] or v)
        conn.execute(update_stmt, {"cfg": json.dumps(out), "id": row.id})
