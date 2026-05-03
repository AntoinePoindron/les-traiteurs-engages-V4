"""Developer tooling — exposed ONLY when ENABLE_DEMO_SEED=1.

Lets you switch between the seeded demo accounts in one click without
having to re-enter passwords. Useful for testing role-specific UI flows.

NEVER ship to production. The endpoint bypasses password verification
entirely and would let any visitor impersonate any user.

Two safeguards keep that risk contained:
  1. The blueprint is only registered by app.py when
     `ENABLE_DEMO_SEED == "1"`. In a prod .deploy.env the flag is empty,
     so the route literally does not exist.
  2. The endpoint additionally hard-codes the demo email allowlist.
     Even if the flag accidentally leaked into prod, only the seven
     well-known demo accounts could be impersonated — not real users.
"""

from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, request, session, url_for
from sqlalchemy import select

from database import get_db
from extensions import limiter
from models import User

devtools_bp = Blueprint("devtools", __name__, url_prefix="/dev")

# Centralised so app.py can pass the same list to the template renderer.
DEMO_ACCOUNTS = [
    {
        "email": "admin@traiteurs-engages.fr",
        "label": "Super Admin",
        "role": "super_admin",
    },
    {
        "email": "alice@acme-solutions.fr",
        "label": "Alice (Acme)",
        "role": "client_admin",
    },
    {"email": "bob@techcorp.fr", "label": "Bob (TechCorp)", "role": "client_admin"},
    {
        "email": "claire@acme-solutions.fr",
        "label": "Claire (Acme)",
        "role": "client_user",
    },
    {
        "email": "contact@saveurs-solidaires.fr",
        "label": "ESAT Saveurs",
        "role": "caterer",
    },
    {"email": "contact@traiteur-co.fr", "label": "EA Traiteur & Co", "role": "caterer"},
    {
        "email": "contact@delices-engages.fr",
        "label": "EI Delices Engages",
        "role": "caterer",
    },
    {
        "email": "contact@marmites-du-sud.fr",
        "label": "EI Marmites du Sud",
        "role": "caterer",
    },
]
_DEMO_EMAILS = {a["email"] for a in DEMO_ACCOUNTS}


@devtools_bp.route("/switch-account", methods=["POST"])
@limiter.exempt  # Dev convenience — flask-limiter shouldn't get in the way here.
def switch_account():
    email = (request.form.get("email") or "").strip().lower()
    if email not in _DEMO_EMAILS:
        abort(403)

    db = get_db()
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        # The seed wasn't run, or the user was deleted. Fail loud so
        # whoever clicked knows the dev DB is in a weird state.
        flash(f"Compte demo introuvable : {email}.", "error")
        return redirect(url_for("auth.login"))

    # Same session rotation as the real /login (audit VULN-11) — fresh
    # session id, no inherited state.
    session.clear()
    session["user_id"] = str(user.id)
    session.permanent = True
    flash(f"[DEV] Connecte en tant que {user.email}.", "info")
    return redirect(url_for("landing"))
