"""Validation rules for CloudDoc uploads."""
from utils.config import ALLOWED_TYPES, MAX_FILE_SIZE_BYTES, MAX_FILENAME_LENGTH


class ValidationError(Exception):
    """Raised when a request or file breaks a rule.

    `code` matches the error codes in docs/api-contract.md.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def get_extension(filename) -> str:
    """Return the lowercase extension of an allowed filename."""
    if not isinstance(filename, str) or not filename.strip():
        raise ValidationError("INVALID_REQUEST", "filename is required.")
    if len(filename) > MAX_FILENAME_LENGTH:
        raise ValidationError("INVALID_REQUEST", "filename is too long.")
    if "/" in filename or "\\" in filename:
        raise ValidationError("INVALID_REQUEST", "filename must not contain path characters.")

    stem, dot, extension = filename.rpartition(".")
    if not dot:
        raise ValidationError("INVALID_FILE_TYPE", "Only PDF and TXT files are supported.")
    if not stem:
        raise ValidationError("INVALID_REQUEST", "filename needs a name before the extension.")

    extension = extension.lower()
    if extension not in ALLOWED_TYPES:
        raise ValidationError("INVALID_FILE_TYPE", "Only PDF and TXT files are supported.")
    return extension


def validate_size(size_bytes) -> None:
    """Check a declared size is a positive integer within the limit."""
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
        raise ValidationError("INVALID_REQUEST", "size_bytes must be a positive integer.")
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise ValidationError(
            "FILE_TOO_LARGE",
            f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB limit.",
        )


def validate_upload_request(filename, content_type, size_bytes) -> str:
    """Layer 1: check the client's claim. Returns the extension."""
    extension = get_extension(filename)
    if content_type != ALLOWED_TYPES[extension]:
        raise ValidationError(
            "INVALID_FILE_TYPE",
            f"content_type must be {ALLOWED_TYPES[extension]} for .{extension} files.",
        )
    validate_size(size_bytes)
    return extension


def validate_file_content(extension: str, content: bytes) -> None:
    """Layer 2: check the real bytes. Does not trust the filename."""
    if not content:
        raise ValidationError("INVALID_REQUEST", "File is empty.")
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise ValidationError("FILE_TOO_LARGE", "File exceeds the size limit.")

    if extension == "pdf":
        if not content.startswith(b"%PDF-"):
            raise ValidationError("INVALID_FILE_TYPE", "File is not a valid PDF.")
    elif extension == "txt":
        if b"\x00" in content:
            raise ValidationError("INVALID_FILE_TYPE", "File is not a text file.")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise ValidationError("INVALID_FILE_TYPE", "Text file must be UTF-8.") from None
    else:
        raise ValidationError("INVALID_FILE_TYPE", "Only PDF and TXT files are supported.")