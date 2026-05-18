"""Audit script — list any demo-seed accounts that ever made it into a
running database.

Audit C-3 follow-up (2026-05-13): removing the postdeploy seeding hook
disarms the ingress, but accounts already created by a prior seed run
keep the same `password123` bcrypt hash forever. This script reads the
canonical seeded emails out of `seed_data.py`'s source (so the list
stays in sync without duplication) and queries the database for any
that still resolve.

Read-only — no writes. Safe to run on prod / staging via
`scalingo --app <name> run python scripts/check_seed_residue.py` or
`docker compose exec app python scripts/check_seed_residue.py` in dev.

Exit code:
  0 — none of the seeded accounts exist in the DB. Clean.
  1 — at least one seeded account is still present. Investigate
      (rotate password or `flask admin disable <email>`).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from sqlalchemy import select

# `database` reads DATABASE_URL at import time — the same env the app
# uses, so this script naturally targets whatever DB the operator has
# pointed their shell at.
from database import session_factory
from models import User

_SEED_FILE = Path(__file__).resolve().parent.parent / "seed_data.py"


def _seeded_emails() -> list[str]:
    """Extract the canonical list of seeded emails directly from
    `seed_data.py`. Keeping a single source of truth avoids drift
    between this audit and the seeder itself."""
    source = _SEED_FILE.read_text(encoding="utf-8")
    # The seeder spells every email as a `email="…@…"` kwarg to User(…).
    return sorted(set(re.findall(r'email="([^"]+@[^"]+)"', source)))


def main() -> int:
    seeded = _seeded_emails()
    if not seeded:
        sys.stderr.write(
            "Could not extract any email from seed_data.py — pattern drifted?\n"
        )
        return 2

    s = session_factory()
    try:
        rows = s.execute(
            select(User.email, User.is_active, User.role).where(User.email.in_(seeded))
        ).all()
    finally:
        s.close()

    if not rows:
        print(f"OK — none of the {len(seeded)} seeded emails exist in this DB.")
        return 0

    print(
        f"FOUND {len(rows)} seeded account(s) in this DB out of {len(seeded)} possible:"
    )
    for email, is_active, role in rows:
        marker = "active" if is_active else "disabled"
        print(f"  - {email}  ({role}, {marker})")
    print(
        "\nNext step: rotate their password (`flask admin reset-password <email>`) "
        "or disable them (`flask admin disable <email>`)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
