"""Extract metadata from a validated document."""
from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfReader

from utils.validators import ValidationError, get_extension, validate_file_content


def count_pdf_pages(content: bytes) -> int:
    try:
        return len(PdfReader(BytesIO(content)).pages)
    except Exception as exc:  # pypdf can raise several error types on bad input
        raise ValidationError("INVALID_FILE_TYPE", "File is not a valid PDF.") from exc


def extract_metadata(filename: str, content: bytes, uploaded_at: str | None = None) -> dict:
    """Validate the bytes, then return the metadata fields from the API contract."""
    extension = get_extension(filename)
    validate_file_content(extension, content)

    return {
        "filename": filename,
        "extension": extension,
        "size_bytes": len(content),
        "uploaded_at": uploaded_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_count": count_pdf_pages(content) if extension == "pdf" else None,
    }