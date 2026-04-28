"""File-upload helper.

Trust nothing the client tells us about the file. Validate:
1. Declared extension is in our allow-list.
2. The actual file content (magic bytes) matches a known image/PDF format.
3. The size is under our per-file cap (global MAX_CONTENT_LENGTH from
   create_app() is the outer layer; this keeps an unrealistic 12 MB logo
   from filling the disk even though it is technically under 16 MB).

Returns None on any rejection so the caller can flash a generic error.
Logs at WARNING for postmortem debugging.

Audit references: VULN-05 (path traversal — uses secure_filename),
VULN-10 (extension-only validation — closed by magic-byte check).
"""
import logging
import os
import uuid

from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
MAX_FILENAME_LENGTH = 80
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file (global cap is 16 MB total request)

# Magic byte signatures. Polyglot files (e.g. an HTML page that begins with
# the PNG signature) are still possible but no consumer of these uploads
# interprets them as HTML — they are served as static images by Flask with
# the right Content-Type. Belt-and-braces would be re-encoding via Pillow,
# tracked as a follow-up.
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


def save_upload(file, subfolder: str = "general") -> str | None:
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

    target_dir = os.path.join(UPLOAD_DIR, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    # secure_filename strips path separators / NUL bytes / parent traversal.
    # Length-cap protects against POSIX 255-byte filename limit and weird unicode.
    clean = secure_filename(file.filename)[:MAX_FILENAME_LENGTH] or "file"
    safe_name = f"{uuid.uuid4().hex}_{clean}"
    file.save(os.path.join(target_dir, safe_name))
    return f"/static/uploads/{subfolder}/{safe_name}"
