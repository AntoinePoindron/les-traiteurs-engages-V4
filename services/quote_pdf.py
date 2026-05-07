"""WeasyPrint-backed PDF rendering for the caterer quote download.

Pulls the same `_pdf_preview.html` partial that drives the in-app
"Voir le devis" modal so the downloaded PDF matches what was on
screen, byte-for-byte content-wise.

The route handler (blueprints/caterer/requests.py::quote_pdf) only
needs to call `render_quote_pdf(quote)` and stream the bytes back
with `Content-Type: application/pdf`.
"""

from __future__ import annotations

import os

from flask import render_template
from weasyprint import CSS, HTML

from models import MEAL_TYPE_LABELS, QuoteRequest
from services.quotes import calculate_quote_totals


_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC_CSS_DIR = os.path.join(_HERE, "static", "css")


def _stylesheets() -> list[CSS]:
    """Read tailwind.css + app.css from disk and return them as
    WeasyPrint CSS objects.

    We deliberately do NOT pass URLs to WeasyPrint: it would HTTP-fetch
    them via urlopen, calling back into gunicorn while we're already
    inside a request handler. On a single-worker dev dyno that's a
    deadlock; on a multi-worker prod dyno it's a wasted hop. Reading
    from disk skips both problems.
    """
    return [
        CSS(filename=os.path.join(_STATIC_CSS_DIR, "tailwind.css")),
        CSS(filename=os.path.join(_STATIC_CSS_DIR, "app.css")),
    ]


def render_quote_pdf(quote) -> bytes:
    """Render `quote` as a PDF and return the bytes.

    Mirrors the `pdf_preview` dict that blueprints/client/requests.py
    builds for the in-app modal — `lines_by_section` + `totals` —
    so the PDF and the modal can't drift visually.
    """
    qr: QuoteRequest = quote.quote_request
    caterer = quote.caterer

    line_dicts = [ln.as_dict() for ln in quote.lines]
    totals = calculate_quote_totals(
        line_dicts,
        qr.guest_count,
        commission_rate=caterer.commission_rate,
    )
    lines_by_section: dict[str, list] = {}
    for ln in quote.lines:
        lines_by_section.setdefault(ln.section, []).append(ln)
    pdf_preview = {
        "lines_by_section": lines_by_section,
        "totals": totals,
    }

    html_str = render_template(
        "caterer/quotes/pdf_document.html",
        quote=quote,
        qr=qr,
        caterer=caterer,
        pdf_preview=pdf_preview,
        meal_type_labels=MEAL_TYPE_LABELS,
    )

    return HTML(string=html_str).write_pdf(stylesheets=_stylesheets())
