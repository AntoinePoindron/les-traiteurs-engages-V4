"""WeasyPrint-backed PDF rendering for the caterer quote download.

Pulls the same `_pdf_preview.html` partial that drives the in-app
"Voir le devis" modal so the downloaded PDF matches what was on
screen, byte-for-byte content-wise.

The route handler (blueprints/caterer/requests.py::quote_pdf) only
needs to call `render_quote_pdf(quote, qr, caterer)` and stream the
bytes back with `Content-Type: application/pdf`. It imports this
module lazily so WeasyPrint's heavy native-binding import (Cairo,
Pango) only happens on a PDF hit, not at app startup.
"""

from __future__ import annotations

import functools
import os

from flask import current_app, render_template
from weasyprint import CSS, HTML
from weasyprint.urls import default_url_fetcher

from models import MEAL_TYPE_LABELS
from services.quotes import build_pdf_preview


# Schemes that have no business appearing during a quote PDF render. We
# don't fetch anything from the network — the HTML is built from a
# Jinja-autoescaped template (no `|safe`) and the stylesheets are
# pre-loaded from disk. Anything trying to reach out is either misuse
# or an injection — fail loud rather than SSRF silently.
_BLOCKED_SCHEMES = ("http://", "https://", "ftp://", "ftps://")


def _safe_fetch(url):
    if url.startswith(_BLOCKED_SCHEMES):
        raise ValueError(f"PDF render refused network fetch: {url!r}")
    return default_url_fetcher(url)


@functools.cache
def _stylesheets() -> tuple[CSS, ...]:
    """Read tailwind.css + app.css from disk once and cache the parsed
    `CSS` objects for the lifetime of the worker.

    We deliberately do NOT pass URLs to WeasyPrint: it would HTTP-fetch
    them via urlopen, calling back into gunicorn while we're already
    inside a request handler. On a single-worker dev dyno that's a
    deadlock; on a multi-worker prod dyno it's a wasted hop. Reading
    from disk skips both problems.
    """
    css_dir = os.path.join(current_app.static_folder, "css")
    return (
        CSS(filename=os.path.join(css_dir, "tailwind.css")),
        CSS(filename=os.path.join(css_dir, "app.css")),
    )


def render_quote_pdf(quote, qr, caterer) -> bytes:
    """Render `quote` as a PDF and return the bytes."""
    pdf_preview = build_pdf_preview(quote, qr, caterer)
    html_str = render_template(
        "caterer/quotes/pdf_document.html",
        quote=quote,
        qr=qr,
        caterer=caterer,
        pdf_preview=pdf_preview,
        meal_type_labels=MEAL_TYPE_LABELS,
    )
    return HTML(string=html_str, url_fetcher=_safe_fetch).write_pdf(
        stylesheets=list(_stylesheets())
    )
