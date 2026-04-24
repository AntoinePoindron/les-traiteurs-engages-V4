import os
import uuid

from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")
MAX_FILENAME_LENGTH = 80


def allowed_extension(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, subfolder="general"):
    if not file or not file.filename or not allowed_extension(file.filename):
        return None
    target_dir = os.path.join(UPLOAD_DIR, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    # secure_filename strips path separators / NUL bytes / parent traversal.
    # Length-cap protects against POSIX 255-byte filename limit and weird unicode.
    clean = secure_filename(file.filename)[:MAX_FILENAME_LENGTH] or "file"
    safe_name = f"{uuid.uuid4().hex}_{clean}"
    file.save(os.path.join(target_dir, safe_name))
    return f"/static/uploads/{subfolder}/{safe_name}"
