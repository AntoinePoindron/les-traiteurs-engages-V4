"""File-upload helper.

Trust nothing the client tells us about the file. Validate:
1. Declared extension is in our allow-list.
2. The actual file content (magic bytes) matches a known image/PDF format.
3. The size is under our per-file cap (global MAX_CONTENT_LENGTH from
   create_app() is the outer layer; this keeps an unrealistic 12 MB logo
   from filling the disk even though it is technically under 16 MB).

Storage backend: S3-compatible when S3_BUCKET is set, local disk otherwise.

Returns None on any rejection so the caller can flash a generic error.
Logs at WARNING for postmortem debugging.

Audit references: VULN-05 (path traversal — uses secure_filename),
VULN-10 (extension-only validation — closed by magic-byte check).
"""
import io
import logging
import os
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
MAX_FILENAME_LENGTH = 80
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file (global cap is 16 MB total request)

_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf",
}

# Magic byte signatures.
_MAGIC_SIGNATURES = {
    "png":  [(b"\x89PNG\r\n\x1a\n", 0)],
    "jpg":  [(b"\xff\xd8\xff", 0)],
    "jpeg": [(b"\xff\xd8\xff", 0)],
    "gif":  [(b"GIF87a", 0), (b"GIF89a", 0)],
    # WEBP files start with "RIFF" then 4 bytes of size then "WEBP"
    "webp": [(b"RIFF", 0), (b"WEBP", 8)],
    "pdf":  [(b"%PDF-", 0)],
}

# Extensions that are interchangeable real-world (same actual format).
_EXTENSION_ALIASES = {
    "jpg":  {"jpg", "jpeg"},
    "jpeg": {"jpg", "jpeg"},
}

# --- S3 client (lazy singleton) ------------------------------------------------

_s3_client = None


def _get_s3():
    global _s3_client
    if _s3_client is None:
        import boto3
        from config import settings
        kwargs = {
            "aws_access_key_id": settings.s3_access_key,
            "aws_secret_access_key": settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None,
            "region_name": settings.s3_region,
        }
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


def _s3_enabled() -> bool:
    from config import settings
    return bool(settings.s3_bucket)


# --- Validation helpers --------------------------------------------------------

def _detect_real_type(head: bytes) -> str | None:
    """Return the extension key that matches the byte signature, or None."""
    for ext, sigs in _MAGIC_SIGNATURES.items():
        if all(head[off:off + len(sig)] == sig for sig, off in sigs):
            return ext
    return None


def _file_size(stream) -> int:
    """Compute size by seeking, then rewind."""
    pos = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(pos)
    return size


def allowed_extension(filename: str) -> bool:
    """Backwards-compat for callers that still want a quick name-only check."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


_PILLOW_FORMAT = {
    "jpg": "JPEG", "jpeg": "JPEG",
    "png": "PNG", "gif": "GIF", "webp": "WEBP",
}

_MAX_IMAGE_PIXELS = 25_000_000  # 5000x5000 — prevent decompression bombs


def _reencode_image(stream, ext: str):
    """Re-encode image through Pillow to strip any embedded payloads.

    Returns a BytesIO with the clean image, or None if re-encoding fails.
    PDFs are not re-encoded.
    """
    fmt = _PILLOW_FORMAT.get(ext)
    if fmt is None:
        return None
    try:
        Image.MAX_IMAGE_PIXELS = _MAX_IMAGE_PIXELS
        img = Image.open(stream)
        img.load()
        if img.mode not in ("RGB", "RGBA", "L", "P"):
            img = img.convert("RGBA" if fmt == "PNG" else "RGB")
        buf = io.BytesIO()
        save_kwargs = {}
        if fmt == "JPEG":
            img = img.convert("RGB")
            save_kwargs["quality"] = 85
        if fmt == "GIF" and getattr(img, "is_animated", False):
            save_kwargs["save_all"] = True
        img.save(buf, format=fmt, **save_kwargs)
        buf.seek(0)
        return buf
    except Exception:
        logger.warning("Pillow re-encode failed for %s", ext, exc_info=True)
        return None


# --- Save (public API) ---------------------------------------------------------

def _validate(file):
    """Validate the upload. Returns (declared_ext, safe_name) or None on rejection."""
    if not file or not file.filename:
        return None

    declared_ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if declared_ext not in ALLOWED_EXTENSIONS:
        logger.warning("upload rejected: extension '%s' not allowed", declared_ext)
        return None

    # Magic-byte check on the first 16 bytes is enough for every supported format.
    head = file.stream.read(16)
    file.stream.seek(0)
    real_ext = _detect_real_type(head)
    if real_ext is None:
        logger.warning("upload rejected: no matching magic bytes (declared %s)", declared_ext)
        return None

    allowed_aliases = _EXTENSION_ALIASES.get(declared_ext, {declared_ext})
    if real_ext not in allowed_aliases:
        logger.warning(
            "upload rejected: magic bytes say %s but extension says %s",
            real_ext, declared_ext,
        )
        return None

    size = _file_size(file.stream)
    if size > MAX_FILE_SIZE:
        logger.warning("upload rejected: %d bytes exceeds %d", size, MAX_FILE_SIZE)
        return None
    if size == 0:
        logger.warning("upload rejected: empty file")
        return None

    clean = secure_filename(file.filename)[:MAX_FILENAME_LENGTH] or "file"
    safe_name = f"{uuid.uuid4().hex}_{clean}"
    return declared_ext, safe_name


def _save_local(file, subfolder: str, safe_name: str) -> str:
    target_dir = os.path.join(UPLOAD_DIR, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    file.save(os.path.join(target_dir, safe_name))
    return f"/static/uploads/{subfolder}/{safe_name}"


def _save_s3(file, subfolder: str, safe_name: str, declared_ext: str) -> str:
    from config import settings
    key = f"uploads/{subfolder}/{safe_name}"
    _get_s3().upload_fileobj(
        file.stream,
        settings.s3_bucket,
        key,
        ExtraArgs={
            "ContentType": _CONTENT_TYPES.get(declared_ext, "application/octet-stream"),
            "CacheControl": "public, max-age=31536000, immutable",
        },
    )
    base = settings.s3_public_url or f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com"
    return f"{base.rstrip('/')}/{key}"


def save_upload(file, subfolder: str = "general") -> str | None:
    result = _validate(file)
    if result is None:
        return None
    declared_ext, safe_name = result

    clean_buf = _reencode_image(file.stream, declared_ext)
    if clean_buf is not None:
        file.stream = clean_buf
    else:
        file.stream.seek(0)

    if _s3_enabled():
        try:
            return _save_s3(file, subfolder, safe_name, declared_ext)
        except (BotoCoreError, ClientError):
            logger.exception("S3 upload failed for %s", safe_name)
            return None

    return _save_local(file, subfolder, safe_name)
