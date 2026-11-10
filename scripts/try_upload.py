"""Manual check: does the real bucket enforce the upload rules?

Run from the repo root:  python -m scripts.try_upload
Needs BUCKET_NAME in the environment and a valid `aws login` session.
"""
import io
import os
import re
import sys
import uuid

import requests
from botocore.exceptions import ClientError
from pypdf import PdfWriter

from src.services import s3_service
from src.utils.config import MAX_FILE_SIZE_BYTES


def make_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def object_exists(bucket: str, key: str) -> bool:
    try:
        s3_service.get_s3_client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def attempt(bucket, filename, claimed_type, content, sent_type=None):
    """Returns (key, response). response is None if S3 closed the connection."""
    form = s3_service.generate_upload_form(bucket, str(uuid.uuid4()), filename, claimed_type)
    fields = dict(form["fields"])
    if sent_type:
        fields["Content-Type"] = sent_type  # lie about the type
    try:
        response = requests.post(
            form["url"], data=fields, files={"file": (filename, content)}, timeout=120
        )
    except requests.exceptions.ConnectionError:
        return form["key"], None
    return form["key"], response


def error_code(response) -> str:
    match = re.search(r"<Code>(.*?)</Code>", response.text)
    return match.group(1) if match else ""


def main() -> int:
    bucket = os.environ.get("BUCKET_NAME")
    if not bucket:
        print("Set BUCKET_NAME first.")
        return 1

    cases = [
        ("valid PDF", "report.pdf", "application/pdf", make_pdf(), None, 204),
        ("valid TXT", "notes.txt", "text/plain", b"hello CloudDoc", None, 204),
        ("oversized TXT", "big.txt", "text/plain", b"a" * (MAX_FILE_SIZE_BYTES + 1), None, 400),
        ("wrong content type", "report.pdf", "application/pdf", make_pdf(), "image/png", 403),
        ("empty file", "empty.txt", "text/plain", b"", None, 400),
    ]

    failures = 0
    for label, filename, claimed, content, sent, expected in cases:
        key, response = attempt(bucket, filename, claimed, content, sent)

        if response is None:
            # S3 rejected early and closed the connection. Rejections are
            # correct only if the file was NOT stored.
            stored = object_exists(bucket, key)
            ok = expected != 204 and not stored
            print(f"{'PASS' if ok else 'FAIL'}  {label:20} connection closed by S3, "
                  f"file stored: {stored}")
            if stored:
                s3_service.delete_object(bucket, key)
        else:
            ok = response.status_code == expected
            print(f"{'PASS' if ok else 'FAIL'}  {label:20} expected {expected}, got "
                  f"{response.status_code} {error_code(response)}")
            if response.status_code == 204:
                stored_bytes = s3_service.get_object_bytes(bucket, key)
                print(f"      stored {len(stored_bytes)} bytes at {key}")
                s3_service.delete_object(bucket, key)
        failures += not ok

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())