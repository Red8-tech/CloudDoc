"""Shared constants for CloudDoc."""
import os

# extension -> required content type
ALLOWED_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain",
}

MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024))  # 10 MB
MAX_FILENAME_LENGTH = 255