"""Public legal pages — CGS (Conditions Générales de Services).

Each version's body lives in a Jinja template under `templates/legal/`.
The `TermsVersion` table is the registry: which slug is current, where
its template lives, when it took effect.

Pages are public on purpose: prospective users must read the CGS before
signing up, and existing users (or anyone) can re-read any past version.
"""

from flask import Blueprint, abort, redirect, render_template, url_for
from sqlalchemy import select

from database import get_db
from models import TermsVersion
from services.terms import current_terms_version


legal_bp = Blueprint("legal", __name__)


@legal_bp.route("/cgs")
def cgs_current():
    """Redirect to the currently-in-force CGS version.

    The 302 (not a direct render) keeps URLs version-stable: a link
    saved today points at /cgs/v1; once /cgs/v2 ships, the new visitors
    land there but the saved link still resolves correctly.
    """
    db = get_db()
    return redirect(url_for("legal.cgs_by_slug", slug=current_terms_version(db).slug))


@legal_bp.route("/cgs/<slug>")
def cgs_by_slug(slug: str):
    db = get_db()
    version = db.scalar(select(TermsVersion).where(TermsVersion.slug == slug))
    if version is None:
        abort(404)
    return render_template(version.template_name, version=version)
