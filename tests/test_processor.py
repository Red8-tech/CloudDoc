import re

import pytest

from src.processor.metadata_extractor import extract_metadata
from src.utils.validators import ValidationError


def test_pdf_metadata(make_pdf):
    content = make_pdf(3)
    result = extract_metadata("report.pdf", content)
    assert result["filename"] == "report.pdf"
    assert result["extension"] == "pdf"
    assert result["size_bytes"] == len(content)
    assert result["page_count"] == 3


def test_txt_metadata_has_no_page_count():
    result = extract_metadata("notes.txt", b"hello")
    assert result["extension"] == "txt"
    assert result["size_bytes"] == 5
    assert result["page_count"] is None


def test_uploaded_at_is_used_when_given():
    result = extract_metadata("notes.txt", b"hello", uploaded_at="2026-11-07T10:15:30Z")
    assert result["uploaded_at"] == "2026-11-07T10:15:30Z"


def test_uploaded_at_defaults_to_utc_iso_format():
    result = extract_metadata("notes.txt", b"hello")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result["uploaded_at"])


def test_pdf_header_with_garbage_body_is_rejected():
    with pytest.raises(ValidationError) as exc:
        extract_metadata("broken.pdf", b"%PDF-1.4 garbage")
    assert exc.value.code == "INVALID_FILE_TYPE"


def test_wrong_extension_is_rejected():
    with pytest.raises(ValidationError) as exc:
        extract_metadata("image.png", b"data")
    assert exc.value.code == "INVALID_FILE_TYPE"