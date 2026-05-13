"""Helpers around CGS (Conditions Générales de Services) versions.

The actual text of each version lives in a Jinja template under
`templates/legal/`. The DB just tracks the metadata (slug, title,
effective_at) and which version each User accepted at signup.
"""

import datetime

from sqlalchemy import select

from models import TermsVersion


def current_terms_version(db) -> TermsVersion:
    """Return the version currently in force.

    "In force" = highest `effective_at` that's <= today. Same-day ties
    are broken by `created_at` (most recent wins) so we can stage a new
    version on its effective date without juggling timezones.

    Raises `RuntimeError` if no row matches — that's a deploy mistake,
    not a runtime condition we want to swallow with a fallback.
    """
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
