"""Tests for the file upload validation and save paths."""

import io

import pytest

from services.uploads import (
    MAX_FILE_SIZE,
    _detect_real_type,
    _validate,
    save_upload,
)

# --- Minimal valid file headers ------------------------------------------------

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 12
GIF_HEADER = b"GIF89a" + b"\x00" * 10
PDF_HEADER = b"%PDF-1.4" + b"\x00" * 8
WEBP_HEADER = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 4


class FakeFile:
    """Minimal stand-in for werkzeug.datastructures.FileStorage."""

    def __init__(self, filename, data):
        self.filename = filename
        self.stream = io.BytesIO(data)

    def save(self, path):
        with open(path, "wb") as f:
            self.stream.seek(0)
            f.write(self.stream.read())


# --- _detect_real_type ---------------------------------------------------------


@pytest.mark.parametrize(
    "ext,header",
    [
        ("png", PNG_HEADER),
        ("jpg", JPEG_HEADER),
        ("gif", GIF_HEADER),
        ("pdf", PDF_HEADER),
        ("webp", WEBP_HEADER),
    ],
)
def test_detect_real_type(ext, header):
    assert _detect_real_type(header) == ext


def test_detect_real_type_unknown():
    assert _detect_real_type(b"\x00" * 16) is None


# --- _validate -----------------------------------------------------------------


def test_validate_accepts_valid_png():
    f = FakeFile("photo.png", PNG_HEADER + b"\x00" * 100)
    result = _validate(f)
    assert result is not None
    declared_ext, safe_name = result
    assert declared_ext == "png"
    assert safe_name.endswith("_photo.png")


def test_validate_accepts_jpg_jpeg_alias():
    f = FakeFile("photo.jpg", JPEG_HEADER + b"\x00" * 100)
    result = _validate(f)
    assert result is not None
    assert result[0] == "jpg"


def test_validate_rejects_disallowed_extension():
    f = FakeFile("script.exe", PNG_HEADER + b"\x00" * 100)
    assert _validate(f) is None


def test_validate_rejects_extension_mismatch():
    """Declared .png but content is JPEG."""
    f = FakeFile("photo.png", JPEG_HEADER + b"\x00" * 100)
    assert _validate(f) is None


def test_validate_rejects_empty_file():
    f = FakeFile("photo.png", b"")
    assert _validate(f) is None


def test_validate_rejects_no_filename():
    f = FakeFile("", PNG_HEADER + b"\x00" * 100)
    assert _validate(f) is None


def test_validate_rejects_none_file():
    assert _validate(None) is None


def test_validate_rejects_oversized_file():
    data = PNG_HEADER + b"\x00" * (MAX_FILE_SIZE + 1)
    f = FakeFile("big.png", data)
    assert _validate(f) is None


def test_validate_rejects_unknown_magic_bytes():
    f = FakeFile("mystery.png", b"\x00" * 100)
    assert _validate(f) is None


# --- save_upload (local path) --------------------------------------------------


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("services.uploads.UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr("services.uploads._s3_enabled", lambda: False)
    return tmp_path


def test_save_upload_local_success(upload_dir):
    f = FakeFile("logo.png", PNG_HEADER + b"\x00" * 100)
    url = save_upload(f, subfolder="test")
    assert url is not None
    assert url.startswith("/static/uploads/test/")
    assert url.endswith("_logo.png")
    # Verify file actually written
    saved = list((upload_dir / "test").iterdir())
    assert len(saved) == 1


def test_save_upload_returns_none_on_invalid(upload_dir):
    f = FakeFile("bad.exe", b"\x00" * 100)
    assert save_upload(f, subfolder="test") is None
    assert not (upload_dir / "test").exists()


def test_save_upload_subfolder_created(upload_dir):
    f = FakeFile("pic.jpg", JPEG_HEADER + b"\x00" * 50)
    url = save_upload(f, subfolder="caterers/logos")
    assert url is not None
    assert (upload_dir / "caterers" / "logos").is_dir()
