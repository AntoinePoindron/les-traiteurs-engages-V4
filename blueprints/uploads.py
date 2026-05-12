"""Proxy route serving objects from the private S3 bucket through Flask.

`services/uploads.py::_save_s3` stores URLs as `/uploads/<key>` rather
than direct Scaleway URLs because the bucket ACL is `private` — a
direct GET would 403. This blueprint reads the object from S3 and
streams it back to the browser, so `<img src="/uploads/...">` keeps
working unchanged in templates.

Trade-offs vs. pre-signed URLs:
  + Single trust boundary: the app decides who sees what (today the
    bucket holds only publicly-shown content like caterer logos, but
    we can add a per-key authz check later without rewriting URLs).
  + Stable URLs cached by the browser (the route returns the same
    bytes for the same key forever — caterer logos are content-
    addressed by uuid, so a new logo means a new key).
  - All bytes transit through Scalingo. For a few hundred KB images
    this is a non-issue; if we ever serve large PDFs at high volume,
    revisit (move those specific keys to pre-signed URLs or a CDN).

The leading-slash form `/uploads/<key>` lives outside `/static/...`
on purpose: nginx/Whitenoise serves `/static/*` straight from disk,
which is exactly what we want for first-party CSS but NOT for
user-uploaded content (we want to keep the Flask hand on it).
"""

import logging

from botocore.exceptions import BotoCoreError, ClientError
from flask import Blueprint, Response, abort, stream_with_context

from services.uploads import _get_s3, _s3_enabled


logger = logging.getLogger(__name__)

uploads_bp = Blueprint("uploads", __name__, url_prefix="/uploads")


# Read in 64 KiB chunks. Smaller wastes Python-side per-iteration
# overhead; larger pins more memory per concurrent request without
# reducing wall time noticeably for typical image sizes.
_STREAM_CHUNK = 64 * 1024


@uploads_bp.route("/<path:key>")
def serve(key: str):
    """Stream an object from the bucket at `uploads/<key>`."""
    if not _s3_enabled():
        # No bucket configured — there's nothing this route can serve.
        # Falling back to filesystem is intentionally NOT done here:
        # files on the legacy filesystem live under `/static/uploads/`
        # and the templates that reference them keep using that prefix.
        abort(404)

    from config import settings

    full_key = f"uploads/{key}"
    try:
        obj = _get_s3().get_object(Bucket=settings.s3_bucket, Key=full_key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        # 404 for missing keys, 502 for anything genuinely broken so the
        # operator notices instead of seeing a sea of fake-404s in logs.
        if code in ("NoSuchKey", "404"):
            abort(404)
        logger.exception("S3 GetObject failed for %s", full_key)
        abort(502)
    except BotoCoreError:
        logger.exception("S3 transport error for %s", full_key)
        abort(502)

    body = obj["Body"]
    headers = {
        # The bucket stores the original content-type at upload time
        # (see _save_s3). Default to `application/octet-stream` if the
        # object somehow lacks one — never trust an upstream field
        # blindly.
        "Content-Type": obj.get("ContentType") or "application/octet-stream",
        # uploads are content-addressed by uuid — bytes never change for
        # a given key, so we can hint aggressive caching downstream.
        "Cache-Control": obj.get("CacheControl")
        or "public, max-age=31536000, immutable",
    }
    length = obj.get("ContentLength")
    if length is not None:
        headers["Content-Length"] = str(length)

    def _generate():
        try:
            while True:
                chunk = body.read(_STREAM_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    return Response(
        stream_with_context(_generate()),
        headers=headers,
        direct_passthrough=True,
    )
