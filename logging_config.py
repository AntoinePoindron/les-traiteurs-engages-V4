"""Structured JSON logging with per-request correlation IDs.

The formatter is `python-json-logger` so each log line is a JSON object —
trivially ingestible by Loki/ELK/Datadog/etc. without a fragile regex parser.

Every HTTP request gets a `g.request_id` (client-provided via
`X-Request-Id` header, or generated if absent) which is added to every
log record emitted during that request via a contextvar filter.
"""
import logging
import logging.config
import uuid
from contextvars import ContextVar

from flask import g, request

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = _request_id.get() or "-"
        return True


LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": RequestIdFilter},
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s",
            "rename_fields": {"asctime": "ts", "levelname": "level", "name": "logger"},
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "root": {"level": "INFO", "handlers": ["stdout"]},
    "loggers": {
        # Reduce gunicorn / werkzeug access-log noise — they re-log what we log.
        "werkzeug": {"level": "WARNING", "handlers": ["stdout"], "propagate": False},
        "gunicorn.access": {"level": "WARNING"},
    },
}


def configure_logging():
    logging.config.dictConfig(LOGGING_CONFIG)


def install_request_id_hooks(app):
    """Wire Flask before/after-request hooks to propagate X-Request-Id."""
    logger = logging.getLogger(__name__)

    @app.before_request
    def _set_request_id():
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
        g.request_id = rid
        _request_id.set(rid)

    @app.after_request
    def _log_request(response):
        # CSRFProtect can short-circuit before our before_request fires, so
        # g.request_id may be missing. Synthesise one so the log line still
        # carries a correlation id.
        rid = g.get("request_id") or _request_id.get() or "-"
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "user_id": str(g.get("current_user").id) if g.get("current_user") else None,
            },
        )
        response.headers.setdefault("X-Request-Id", rid)
        return response
