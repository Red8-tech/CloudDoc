import pytest

from src.utils.config import MAX_FILE_SIZE_BYTES
from src.utils.validators import (
    ValidationError,
    get_extension,
    validate_file_content,
    validate_size,
    validate_upload_request,
)


@pytest.mark.parametrize("filename,expected", [
    ("report.pdf", "pdf"),
    ("NOTES.TXT", "txt"),
    ("my.report.final.pdf", "pdf"),
])
def test_get_extension_accepts_allowed_files(filename, expected):
    assert get_extension(filename) == expected


@pytest.mark.parametrize("filename,code", [
    ("image.png", "INVALID_FILE_TYPE"),
    ("noextension", "INVALID_FILE_TYPE"),
    ("", "INVALID_REQUEST"),
    ("   ", "INVALID_REQUEST"),
    (".pdf", "INVALID_REQUEST"),
    ("a/b.pdf", "INVALID_REQUEST"),
    ("x" * 300 + ".pdf", "INVALID_REQUEST"),
    (None, "INVALID_REQUEST"),
])
def test_get_extension_rejects_bad_filenames(filename, code):
    with pytest.raises(ValidationError) as exc:
        get_extension(filename)
    assert exc.value.code == code


@pytest.mark.parametrize("size", [1, 1024, MAX_FILE_SIZE_BYTES])
def test_validate_size_accepts_valid_sizes(size):
    validate_size(size)


@pytest.mark.parametrize("size,code", [
    (MAX_FILE_SIZE_BYTES + 1, "FILE_TOO_LARGE"),
    (0, "INVALID_REQUEST"),
    (-5, "INVALID_REQUEST"),
    ("100", "INVALID_REQUEST"),
    (1.5, "INVALID_REQUEST"),
    (True, "INVALID_REQUEST"),
])
def test_validate_size_rejects_bad_sizes(size, code):
    with pytest.raises(ValidationError) as exc:
        validate_size(size)
    assert exc.value.code == code


def test_upload_request_returns_extension():
    assert validate_upload_request("report.pdf", "application/pdf", 2048) == "pdf"


def test_upload_request_rejects_mismatched_content_type():
    with pytest.raises(ValidationError) as exc:
        validate_upload_request("report.pdf", "text/plain", 2048)
    assert exc.value.code == "INVALID_FILE_TYPE"


def test_content_accepts_real_pdf(make_pdf):
    validate_file_content("pdf", make_pdf(2))


def test_content_rejects_fake_pdf():
    with pytest.raises(ValidationError) as exc:
        validate_file_content("pdf", b"this is not a pdf")
    assert exc.value.code == "INVALID_FILE_TYPE"


def test_content_accepts_utf8_text():
    validate_file_content("txt", "hello, world".encode("utf-8"))


def test_content_rejects_binary_text():
    with pytest.raises(ValidationError) as exc:
        validate_file_content("txt", b"\xff\xfe\x00\x01")
    assert exc.value.code == "INVALID_FILE_TYPE"


def test_content_rejects_empty_file():
    with pytest.raises(ValidationError) as exc:
        validate_file_content("txt", b"")
    assert exc.value.code == "INVALID_REQUEST"


def test_content_rejects_oversized_file():
    with pytest.raises(ValidationError) as exc:
        validate_file_content("txt", b"a" * (MAX_FILE_SIZE_BYTES + 1))
    assert exc.value.code == "FILE_TOO_LARGE"


def test_content_rejects_invalid_utf8_without_null_bytes():
    # "café" encoded as Latin-1, which is not valid UTF-8
    with pytest.raises(ValidationError) as exc:
        validate_file_content("txt", b"caf\xe9")
    assert exc.value.code == "INVALID_FILE_TYPE"
    assert "UTF-8" in exc.value.message


def test_content_rejects_unsupported_extension():
    with pytest.raises(ValidationError) as exc:
        validate_file_content("png", b"data")
    assert exc.value.code == "INVALID_FILE_TYPE"