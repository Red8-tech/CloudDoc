"""Thin wrapper around S3 for CloudDoc."""
import boto3
from botocore.config import Config

from utils import config


def get_s3_client():
    """Regional client with SigV4, which regional buckets require for presigned POST."""
    return boto3.client(
        "s3",
        region_name=config.REGION,
        config=Config(signature_version="s3v4"),
    )


def build_object_key(document_id: str, filename: str) -> str:
    """uploads/{document_id}/{filename}, as defined in docs/data-model.md."""
    return f"{config.UPLOAD_PREFIX}{document_id}/{filename}"


def document_id_from_key(key: str) -> str:
    """Recover the document ID from an object key (used by the worker in Week 5)."""
    parts = key.split("/", 2)
    if len(parts) != 3 or f"{parts[0]}/" != config.UPLOAD_PREFIX or not parts[1] or not parts[2]:
        raise ValueError(f"Unexpected object key: {key!r}")
    return parts[1]


def generate_upload_form(
    bucket: str,
    document_id: str,
    filename: str,
    content_type: str,
    expires_in: int = config.UPLOAD_URL_EXPIRY_SECONDS,
    client=None,
) -> dict:
    """Create a presigned POST form. S3 enforces the content type and size range."""
    client = client or get_s3_client()
    key = build_object_key(document_id, filename)
    form = client.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, config.MAX_FILE_SIZE_BYTES],
        ],
        ExpiresIn=expires_in,
    )
    return {"url": form["url"], "fields": form["fields"], "key": key}


def get_object_bytes(bucket: str, key: str, client=None) -> bytes:
    client = client or get_s3_client()
    return client.get_object(Bucket=bucket, Key=key)["Body"].read()


def delete_object(bucket: str, key: str, client=None) -> None:
    client = client or get_s3_client()
    client.delete_object(Bucket=bucket, Key=key)