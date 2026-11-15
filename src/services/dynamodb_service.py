"""DynamoDB access for CloudDoc document records (see docs/data-model.md)."""
import boto3
from botocore.exceptions import ClientError

from utils import config
from utils.clock import now_iso

PENDING = "PENDING"
PROCESSING = "PROCESSING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

# Outcomes of start_processing
STARTED = "STARTED"
ALREADY_DONE = "ALREADY_DONE"
NOT_FOUND = "NOT_FOUND"


def get_table():
    return boto3.resource("dynamodb", region_name=config.REGION).Table(config.TABLE_NAME)


def _condition_failed(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"


def create_document(*, document_id, filename, extension, content_type,
                    size_bytes, s3_key, uploaded_at, expires_at) -> None:
    """Create a PENDING record. Fails if the ID already exists."""
    get_table().put_item(
        Item={
            "document_id": document_id,
            "status": PENDING,
            "filename": filename,
            "extension": extension,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "s3_key": s3_key,
            "uploaded_at": uploaded_at,
            "expires_at": expires_at,
        },
        ConditionExpression="attribute_not_exists(document_id)",
    )


def get_document(document_id: str):
    """Return the record, or None. Consistent read, so a status poll sees the latest write."""
    response = get_table().get_item(Key={"document_id": document_id}, ConsistentRead=True)
    return response.get("Item")


def start_processing(document_id: str):
    """Move PENDING (or a crashed PROCESSING) to PROCESSING and drop the TTL.

    Returns (STARTED, record), (ALREADY_DONE, record) or (NOT_FOUND, None).
    """
    table = get_table()
    try:
        response = table.update_item(
            Key={"document_id": document_id},
            UpdateExpression="SET #s = :processing REMOVE expires_at",
            ConditionExpression=(
                "attribute_exists(document_id) AND (#s = :pending OR #s = :processing)"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":processing": PROCESSING, ":pending": PENDING},
            ReturnValues="ALL_NEW",
        )
        return STARTED, response["Attributes"]
    except ClientError as exc:
        if not _condition_failed(exc):
            raise

    item = get_document(document_id)
    return (ALREADY_DONE, item) if item else (NOT_FOUND, None)


def _finish(document_id: str, update_expression: str, values: dict) -> bool:
    """Final status change, allowed only from PROCESSING. False if it was not PROCESSING."""
    try:
        get_table().update_item(
            Key={"document_id": document_id},
            UpdateExpression=update_expression,
            ConditionExpression="#s = :processing",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":processing": PROCESSING, **values},
        )
        return True
    except ClientError as exc:
        if _condition_failed(exc):
            return False
        raise


def mark_completed(document_id: str, size_bytes: int, page_count=None) -> bool:
    update = "SET #s = :completed, size_bytes = :size, processed_at = :now"
    values = {":completed": COMPLETED, ":size": size_bytes, ":now": now_iso()}
    if page_count is not None:  # TXT files have no page count: leave the attribute out
        update += ", page_count = :pages"
        values[":pages"] = page_count
    return _finish(document_id, update, values)


def mark_failed(document_id: str, error_message: str) -> bool:
    return _finish(
        document_id,
        "SET #s = :failed, error_message = :msg, processed_at = :now",
        {":failed": FAILED, ":msg": error_message, ":now": now_iso()},
    )