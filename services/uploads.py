import os
import uuid

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "pdf"}
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads")


def allowed_extension(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, subfolder="general"):
    if not file or not file.filename or not allowed_extension(file.filename):
        return None
    target_dir = os.path.join(UPLOAD_DIR, subfolder)
    os.makedirs(target_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{file.filename}"
    file.save(os.path.join(target_dir, safe_name))
    return f"/static/uploads/{subfolder}/{safe_name}"
