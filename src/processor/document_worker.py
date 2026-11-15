"""SQS worker: validate each uploaded document and extract its metadata."""
import json
import logging
from urllib.parse import unquote_plus

from botocore.exceptions import ClientError

from processor.metadata_extractor import extract_metadata
from services import dynamodb_service, s3_service
from utils.validators import ValidationError

logger = logging.getLogger()


def _skipped(document_id: str) -> dict:
    return {"document_id": document_id, "status": "SKIPPED"}


def _fail(bucket: str, key: str, document_id: str, code: str, message: str) -> dict:
    """Record the failure first (the record is the source of truth), then delete the file."""
    if not dynamodb_service.mark_failed(document_id, message):
        logger.info("Document %s was already finalized; skipping", document_id)
        return _skipped(document_id)
    s3_service.delete_object(bucket, key)
    logger.warning("Document %s failed (%s): %s", document_id, code, message)
    return {
        "document_id": document_id,
        "status": "FAILED",
        "error_code": code,
        "error_message": message,
    }


def process_object(bucket: str, key: str) -> dict:
    """Process one uploaded object. Raises on transient errors so SQS retries."""
    document_id = s3_service.document_id_from_key(key)  # ValueError if malformed
    filename = key.split("/", 2)[2]

    outcome, record = dynamodb_service.start_processing(document_id)
    if outcome == dynamodb_service.NOT_FOUND:
        logger.warning("No record for document %s; deleting the orphan file", document_id)
        s3_service.delete_object(bucket, key)
        return _skipped(document_id)
    if outcome == dynamodb_service.ALREADY_DONE:
        if record["status"] == dynamodb_service.FAILED:
            s3_service.delete_object(bucket, key)  # finish a delete a crash may have interrupted
        logger.info("Document %s is already %s; skipping", document_id, record["status"])
        return _skipped(document_id)

    try:
        content = s3_service.get_object_bytes(bucket, key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchKey":
            raise  # possibly transient: let SQS retry
        return _fail(bucket, key, document_id, "FILE_MISSING", "Uploaded file was not found.")

    try:
        metadata = extract_metadata(filename, content, uploaded_at=record["uploaded_at"])
    except ValidationError as exc:
        return _fail(bucket, key, document_id, exc.code, exc.message)

    if not dynamodb_service.mark_completed(
        document_id, metadata["size_bytes"], metadata["page_count"]
    ):
        logger.info("Document %s was already finalized; skipping", document_id)
        return _skipped(document_id)

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