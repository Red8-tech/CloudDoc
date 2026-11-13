"""SQS worker: validate each uploaded document and extract its metadata.

Week 5 logs the result. Week 6 adds DynamoDB status updates.
"""
import json
import logging
from urllib.parse import unquote_plus

from botocore.exceptions import ClientError

from processor.metadata_extractor import extract_metadata
from services import s3_service
from utils.validators import ValidationError

logger = logging.getLogger()


def process_object(bucket: str, key: str) -> dict:
    """Process one uploaded object. Raises on transient or malformed input."""
    document_id = s3_service.document_id_from_key(key)  # ValueError if malformed
    filename = key.split("/", 2)[2]

    try:
        content = s3_service.get_object_bytes(bucket, key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "NoSuchKey":
            # Duplicate delivery or an already-removed file: nothing left to do.
            logger.warning("Object %s no longer exists; skipping", key)
            return {"document_id": document_id, "status": "SKIPPED"}
        raise  # anything else may be transient: let SQS retry

    try:
        metadata = extract_metadata(filename, content)
    except ValidationError as exc:
        # Permanent failure: retrying cannot help, so remove the file.
        s3_service.delete_object(bucket, key)
        logger.warning("Document %s failed validation (%s); file deleted", document_id, exc.code)
        return {
            "document_id": document_id,
            "status": "FAILED",
            "error_code": exc.code,
            "error_message": exc.message,
        }

    logger.info("Document %s processed: %s", document_id, json.dumps(metadata))
    return {"document_id": document_id, "status": "COMPLETED", "metadata": metadata}


def process_message(body: str) -> list:
    """Handle one SQS message body, which holds an S3 event notification."""
    message = json.loads(body)

    if message.get("Event") == "s3:TestEvent":
        logger.info("Ignoring S3 test event")
        return []

    results = []
    for record in message["Records"]:
        event_name = record.get("eventName", "")
        if not event_name.startswith("ObjectCreated"):
            logger.info("Ignoring event %s", event_name)
            continue
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])  # S3 URL-encodes keys
        results.append(process_object(bucket, key))
    return results


def lambda_handler(event, context):
    """Partial batch response: only the failed messages go back to the queue."""
    failures = []
    for sqs_record in event.get("Records", []):
        message_id = sqs_record["messageId"]
        try:
            process_message(sqs_record["body"])
        except Exception:
            logger.exception("Failed to process message %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}