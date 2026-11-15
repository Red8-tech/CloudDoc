"""POST /documents: validate the request and return a presigned S3 upload form."""
import base64
import json
import logging
import uuid

from services import dynamodb_service, s3_service
from utils import clock, config
from utils.responses import error_response, json_response
from utils.validators import ValidationError, validate_upload_request

logger = logging.getLogger()


def _parse_body(event: dict) -> dict:
    body = event.get("body")
    if not body:
        raise ValidationError("INVALID_REQUEST", "Request body is required.")

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except ValueError:
            raise ValidationError("INVALID_REQUEST", "Request body could not be decoded.") from None

    try:
        data = json.loads(body)
    except ValueError:
        raise ValidationError("INVALID_REQUEST", "Request body must be valid JSON.") from None

    if not isinstance(data, dict):
        raise ValidationError("INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def lambda_handler(event, context):
    try:
        data = _parse_body(event)
        extension = validate_upload_request(
            data.get("filename"), data.get("content_type"), data.get("size_bytes")
        )

        if not config.BUCKET_NAME or not config.TABLE_NAME:
            raise RuntimeError("BUCKET_NAME or TABLE_NAME is not configured")

        document_id = str(uuid.uuid4())
        form = s3_service.generate_upload_form(
            config.BUCKET_NAME, document_id, data["filename"], data["content_type"]
        )
        dynamodb_service.create_document(
            document_id=document_id,
            filename=data["filename"],
            extension=extension,
            content_type=data["content_type"],
            size_bytes=data["size_bytes"],
            s3_key=form["key"],
            uploaded_at=clock.now_iso(),
            expires_at=clock.now_epoch() + config.PENDING_TTL_SECONDS,
        )
        logger.info("Created document %s", document_id)

        return json_response(201, {
            "document_id": document_id,
            "status": "PENDING",
            "upload": {"url": form["url"], "fields": form["fields"]},
            "expires_in": config.UPLOAD_URL_EXPIRY_SECONDS,
        })
    except ValidationError as exc:
        logger.info("Rejected upload request: %s", exc.code)
        return error_response(exc.code, exc.message)
    except Exception:
        logger.exception("Unexpected error while creating upload form")
        return error_response("INTERNAL_ERROR", "Something went wrong. Please try again.")