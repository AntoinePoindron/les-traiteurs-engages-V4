"""Helpers around CGS (Conditions Générales de Services) versions.

The actual text of each version lives in a Jinja template under
`templates/legal/`. The DB just tracks the metadata (slug, title,
effective_at) and which version each User accepted at signup.
"""

import datetime

from sqlalchemy import select

from models import TermsVersion


def is_terms_accepted(form) -> bool:
    """Return True iff the POST body carries an opt-in `accept_terms`.

    HTML checkboxes emit `on` when ticked and nothing when not; we also
    accept `1` / `true` so a non-browser caller (curl, integration
    tests) can express acceptance explicitly. Anything else — including
    omitting the field — is treated as refusal so the server gate
    fail-closes rather than fail-opens on tampered or stale forms.
    """
    return (form.get("accept_terms") or "").strip().lower() in ("on", "1", "true")


def current_terms_version(db, today: datetime.date | None = None) -> TermsVersion:
    """Return the version currently in force.

    "In force" = highest `effective_at` that's <= today. Same-day ties
    are broken by `created_at` (most recent wins) so we can stage a new
    version on its effective date without juggling timezones.

    `today` defaults to `datetime.date.today()`; passing it explicitly
    is the test seam (avoids `freeze_time` for unit tests).

    Raises `RuntimeError` if no row matches — that's a deploy mistake,
    not a runtime condition we want to swallow with a fallback.
    """
    if today is None:
        today = datetime.date.today()
    row = db.scalar(
        select(TermsVersion)
        .where(TermsVersion.effective_at <= today)
        .order_by(
            TermsVersion.effective_at.desc(),
            TermsVersion.created_at.desc(),
        )
        .limit(1)
    )
    if row is None:
        raise RuntimeError(
            "No TermsVersion in force today — check the alembic seed migration."
        )
    return row
