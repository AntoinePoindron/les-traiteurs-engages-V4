"""Transactional email — Brevo HTTP adapter + dramatiq actor.

Two entry points :

* `send_email_async.send(to, subject, html, text=...)`
      Queues a send via dramatiq. Use this from request handlers — non
      blocking, retried on failure.

* `send_email_sync(...)`
      Calls Brevo synchronously. Used by the dramatiq actor itself, by
      tests, and as a low-level escape hatch.

Two operating modes :

* `BREVO_API_KEY` set → POSTs to Brevo's transactional endpoint. On
  HTTP errors the dramatiq retry policy re-enqueues with exponential
  backoff. Non-retryable errors (400 with a permanent reason) are
  logged and dropped.
* `BREVO_API_KEY` empty (dev / CI / staging without a key) → logs the
  payload (subject, recipient, body excerpt) at INFO level and returns
  cleanly. The route still works end-to-end so flows like password
  reset can be tested without a real account; only the actual
  delivery is skipped.

Brevo API : https://developers.brevo.com/reference/sendtransacemail
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

import dramatiq

import config

# Importing `services.billing_tasks` has the side-effect of configuring
# the dramatiq broker (Redis in normal runs, StubBroker in tests).
# We piggy-back on its setup so this module doesn't have to duplicate
# the broker bootstrap. The import is cheap (no DB, no Stripe SDK call
# at import time — billing_tasks defers those into the actor body).
from services import billing_tasks  # noqa: F401

logger = logging.getLogger(__name__)


_BREVO_ENDPOINT = "https://api.brevo.com/v3/smtp/email"


class EmailSendError(Exception):
    """Raised by `send_email_sync` for retryable Brevo failures (5xx,
    network, timeouts). The dramatiq actor catches this and lets the
    framework retry. Permanent failures (4xx other than 429) are logged
    and dropped without raising — retrying won't help."""


def _normalise_recipients(to) -> list[dict]:
    """Brevo expects `[{"email": "...", "name": "..."}]`. Accept either a
    bare email string or a list of strings/tuples. Names default to the
    email when not provided."""
    if isinstance(to, str):
        return [{"email": to}]
    out: list[dict] = []
    for entry in to:
        if isinstance(entry, str):
            out.append({"email": entry})
        elif isinstance(entry, dict):
            out.append(entry)
        else:
            email, name = entry
            out.append({"email": email, "name": name})
    return out


def _post_to_brevo(payload: dict, api_key: str, *, timeout: float = 10.0) -> None:
    """POST `payload` to the Brevo transactional endpoint. Raise
    `EmailSendError` on retryable failures, return None on success.

    Permanent failures (the API rejecting the payload structure or the
    sender domain) are logged and swallowed — retrying won't help and
    we don't want to flood the dead-letter queue with the same broken
    payload."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _BREVO_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return
            # Should be unreachable — urlopen raises HTTPError on 4xx/5xx.
            raise EmailSendError(f"unexpected Brevo status {resp.status}")
    except urllib.error.HTTPError as exc:
        body_excerpt = ""
        try:
            body_excerpt = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        if exc.code == 429 or 500 <= exc.code < 600:
            # Rate-limited or server error → retry.
            raise EmailSendError(f"Brevo HTTP {exc.code}: {body_excerpt}") from exc
        # 4xx other than 429 = permanent. Log + swallow.
        logger.error(
            "Brevo rejected email (status=%s, body=%s, subject=%s, to=%s)",
            exc.code,
            body_excerpt,
            payload.get("subject"),
            [r.get("email") for r in payload.get("to", [])],
        )
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmailSendError(f"Brevo network error: {exc}") from exc


def send_email_sync(
    *,
    to,
    subject: str,
    html: str,
    text: str | None = None,
    sender_email: str | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> None:
    """Synchronously deliver one email.

    `to` accepts a string, a list of strings, or a list of
    `(email, name)` tuples / `{"email", "name"}` dicts. `text` is the
    plain-text alt body; falls back to a stripped HTML if absent.
    """
    recipients = _normalise_recipients(to)
    sender = {
        "email": sender_email or config.MAIL_FROM_EMAIL,
        "name": sender_name or config.MAIL_FROM_NAME,
    }
    payload = {
        "sender": sender,
        "to": recipients,
        "subject": subject,
        "htmlContent": html,
        "textContent": text or _html_to_text(html),
    }
    if reply_to:
        payload["replyTo"] = {"email": reply_to}

    api_key = config.BREVO_API_KEY
    if not api_key:
        # Dev / CI fallback — log the payload so flows can be exercised
        # end-to-end without a real Brevo account. 500 chars is enough
        # to surface a full reset URL (token ≈ 43 chars URL-safe base64).
        logger.info(
            "BREVO_API_KEY unset; would have sent email "
            "(subject=%r, to=%s, body_excerpt=%r)",
            subject,
            [r["email"] for r in recipients],
            (text or _html_to_text(html))[:500],
        )
        return

    _post_to_brevo(payload, api_key)


def _html_to_text(html: str) -> str:
    """Crude HTML→text fallback for the multipart alt body. Strips
    every tag and collapses whitespace. Good enough for transactional
    emails where the HTML is already simple."""
    import re

    no_tags = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", no_tags).strip()


# --- Dramatiq actor -------------------------------------------------------
#
# Importing `services.billing_tasks` is what configures the broker for
# the whole app. We rely on that side-effect having happened by the time
# `send_email_async.send(...)` is called from a request handler.
# `os.getenv("DRAMATIQ_TESTING")` lets us no-op the queue in unit tests
# that just want to check the route flow without spinning up a worker.


@dramatiq.actor(
    max_retries=5,
    # Same backoff curve as billing tasks: 30s, 1m, 2m, 4m, 8m, then DLQ.
    min_backoff=30_000,
    max_backoff=8 * 60_000,
    throws=(),
)
def send_email_async(
    *,
    to,
    subject: str,
    html: str,
    text: str | None = None,
    sender_email: str | None = None,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> None:
    """Dramatiq actor wrapping `send_email_sync`. Retryable failures
    (network, 5xx, 429) re-raise so the framework retries; permanent
    failures are already swallowed inside `_post_to_brevo`."""
    if os.getenv("DRAMATIQ_TESTING") == "1":
        # Tests: forward to the sync path. Avoids spinning up the stub
        # broker worker just for unit-level coverage of email triggers.
        send_email_sync(
            to=to,
            subject=subject,
            html=html,
            text=text,
            sender_email=sender_email,
            sender_name=sender_name,
            reply_to=reply_to,
        )
        return

    send_email_sync(
        to=to,
        subject=subject,
        html=html,
        text=text,
        sender_email=sender_email,
        sender_name=sender_name,
        reply_to=reply_to,
    )


# --- Convenience helper ---------------------------------------------------


def render_and_send_async(
    *,
    to,
    subject: str,
    template_name: str,
    **context,
) -> None:
    """Render `templates/emails/{template_name}.{html,txt}` with the
    given context and queue the email.

    Caller MUST be inside a Flask app/request context (we render
    synchronously here so the worker doesn't need its own context). The
    rendered strings travel through the dramatiq message; the worker's
    `send_email_async` actor only needs to POST to Brevo.

    Keeps the four-line "render html + render txt + send_email_async.send"
    boilerplate out of every route handler.
    """
    from flask import render_template

    html = render_template(f"emails/{template_name}.html", **context)
    text = render_template(f"emails/{template_name}.txt", **context)
    send_email_async.send(to=to, subject=subject, html=html, text=text)
