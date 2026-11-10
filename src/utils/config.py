"""Shared constants for CloudDoc."""
import os

# extension -> required content type
ALLOWED_TYPES = {
    "pdf": "application/pdf",
    "txt": "text/plain",
}

MAX_FILE_SIZE_BYTES = int(os.environ.get("MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024))  # 10 MB
MAX_FILENAME_LENGTH = 255

REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-2"
BUCKET_NAME = os.environ.get("BUCKET_NAME", "")
UPLOAD_PREFIX = "uploads/"
UPLOAD_URL_EXPIRY_SECONDS = 300  # 5 minutes, as in the requirements