"""GET /documents/{document_id}: return a document's status and metadata."""
import logging
import uuid

from services import dynamodb_service
from utils.responses import error_response, json_response

logger = logging.getLogger()


def _is_valid_id(value) -> bool:
    try:
        return str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def to_api_view(record: dict) -> dict:
    """The fields in docs/api-contract.md. Internal fields (s3_key, expires_at) stay private."""
    return {
        "document_id": record["document_id"],
        "status": record["status"],
        "filename": record["filename"],
        "extension": record["extension"],
        "size_bytes": int(record["size_bytes"]),
        "page_count": int(record["page_count"]) if "page_count" in record else None,
        "uploaded_at": record["uploaded_at"],
        "processed_at": record.get("processed_at"),
        "error_message": record.get("error_message"),
    }


def lambda_handler(event, context):
    try:
        document_id = (event.get("pathParameters") or {}).get("document_id")
        if not _is_valid_id(document_id):
            return error_response("NOT_FOUND", "Document not found.")

        record = dynamodb_service.get_document(document_id)
        if record is None:
            return error_response("NOT_FOUND", "Document not found.")
        return json_response(200, to_api_view(record))
    except Exception:
        logger.exception("Unexpected error while reading document status")
        return error_response("INTERNAL_ERROR", "Something went wrong. Please try again.")