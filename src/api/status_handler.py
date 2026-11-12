"""GET /documents/{document_id}: DynamoDB lookup arrives in Week 6."""
import logging
import uuid

from utils.responses import error_response, json_response

logger = logging.getLogger()


def _is_valid_id(value) -> bool:
    try:
        return str(uuid.UUID(value)) == value.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def find_document(document_id: str):
    """Placeholder. Week 6 replaces this with a DynamoDB lookup."""
    return None


def lambda_handler(event, context):
    try:
        document_id = (event.get("pathParameters") or {}).get("document_id")
        if not _is_valid_id(document_id):
            return error_response("NOT_FOUND", "Document not found.")

        document = find_document(document_id)
        if document is None:
            return error_response("NOT_FOUND", "Document not found.")
        return json_response(200, document)
    except Exception:
        logger.exception("Unexpected error while reading document status")
        return error_response("INTERNAL_ERROR", "Something went wrong. Please try again.")