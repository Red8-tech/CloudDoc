import base64
import json
import time
import uuid

import pytest

from api import status_handler, upload_handler
from services import dynamodb_service as db
from utils import config

pytestmark = pytest.mark.usefixtures("aws")

DOC_ID = "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10"


def valid_body(**overrides):
    body = {"filename": "report.pdf", "content_type": "application/pdf", "size_bytes": 2048}
    body.update(overrides)
    return body


def call_upload(body):
    if body is not None and not isinstance(body, str):
        body = json.dumps(body)
    response = upload_handler.lambda_handler({"body": body, "isBase64Encoded": False}, None)
    return response["statusCode"], json.loads(response["body"]), response


def call_status(document_id):
    response = status_handler.lambda_handler({"pathParameters": {"document_id": document_id}}, None)
    return response["statusCode"], json.loads(response["body"])


def add_record(**overrides):
    fields = dict(
        document_id=DOC_ID, filename="report.pdf", extension="pdf",
        content_type="application/pdf", size_bytes=2048,
        s3_key=f"uploads/{DOC_ID}/report.pdf",
        uploaded_at="2026-11-13T07:00:00Z", expires_at=1900000000,
    )
    fields.update(overrides)
    db.create_document(**fields)


# ---- POST /documents ----

def test_upload_success_returns_a_form():
    status, body, response = call_upload(valid_body())
    assert status == 201
    assert response["headers"]["Content-Type"] == "application/json"
    assert uuid.UUID(body["document_id"]).version == 4
    assert body["status"] == "PENDING"
    assert body["expires_in"] == 300
    assert "clouddoc-test-bucket" in body["upload"]["url"]
    assert body["upload"]["fields"]["key"] == f"uploads/{body['document_id']}/report.pdf"
    assert body["upload"]["fields"]["Content-Type"] == "application/pdf"


def test_upload_creates_a_pending_record():
    _, body, _ = call_upload(valid_body())
    item = db.get_document(body["document_id"])
    assert item["status"] == "PENDING"
    assert item["filename"] == "report.pdf"
    assert item["extension"] == "pdf"
    assert item["s3_key"] == body["upload"]["fields"]["key"]
    assert item["uploaded_at"].endswith("Z")
    # the record expires in about 24 hours unless a worker picks it up
    assert abs(int(item["expires_at"]) - (time.time() + 86400)) < 60


def test_upload_success_for_txt():
    status, body, _ = call_upload(valid_body(filename="notes.txt", content_type="text/plain"))
    assert status == 201
    assert db.get_document(body["document_id"])["extension"] == "txt"


def test_each_request_gets_a_new_document_id():
    ids = {call_upload(valid_body())[1]["document_id"] for _ in range(3)}
    assert len(ids) == 3


def test_base64_body_is_decoded():
    encoded = base64.b64encode(json.dumps(valid_body()).encode()).decode()
    response = upload_handler.lambda_handler({"body": encoded, "isBase64Encoded": True}, None)
    assert response["statusCode"] == 201


@pytest.mark.parametrize("body,code", [
    (None, "INVALID_REQUEST"),
    ("", "INVALID_REQUEST"),
    ("not json", "INVALID_REQUEST"),
    ("[1, 2]", "INVALID_REQUEST"),
    ({}, "INVALID_REQUEST"),
    (valid_body(filename="image.png", content_type="image/png"), "INVALID_FILE_TYPE"),
    (valid_body(content_type="text/plain"), "INVALID_FILE_TYPE"),
    (valid_body(size_bytes=config.MAX_FILE_SIZE_BYTES + 1), "FILE_TOO_LARGE"),
    (valid_body(size_bytes=0), "INVALID_REQUEST"),
    (valid_body(size_bytes="100"), "INVALID_REQUEST"),
])
def test_bad_requests_use_the_documented_error_shape(aws, body, code):
    status, payload, _ = call_upload(body)
    assert status == 400
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]
    assert aws.table.scan()["Items"] == []  # rejected requests leave no record


def test_s3_failure_returns_generic_500_and_no_record(aws, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(upload_handler.s3_service, "generate_upload_form", boom)
    status, payload, response = call_upload(valid_body())
    assert status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response["body"]
    assert aws.table.scan()["Items"] == []


def test_dynamodb_failure_returns_generic_500(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(upload_handler.dynamodb_service, "create_document", boom)
    status, payload, response = call_upload(valid_body())
    assert status == 500
    assert "secret" not in response["body"]


def test_missing_settings_return_500(monkeypatch):
    monkeypatch.setattr(config, "TABLE_NAME", "")
    status, payload, _ = call_upload(valid_body())
    assert status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"


# ---- GET /documents/{id} ----

def test_status_of_a_pending_document():
    add_record()
    status, body = call_status(DOC_ID)
    assert status == 200
    assert body == {
        "document_id": DOC_ID, "status": "PENDING", "filename": "report.pdf",
        "extension": "pdf", "size_bytes": 2048, "page_count": None,
        "uploaded_at": "2026-11-13T07:00:00Z", "processed_at": None, "error_message": None,
    }


def test_status_of_a_completed_pdf():
    add_record()
    db.start_processing(DOC_ID)
    db.mark_completed(DOC_ID, 551, 2)
    status, body = call_status(DOC_ID)
    assert status == 200
    assert body["status"] == "COMPLETED"
    assert body["size_bytes"] == 551
    assert body["page_count"] == 2
    assert body["processed_at"].endswith("Z")
    assert body["error_message"] is None


def test_status_of_a_failed_document():
    add_record()
    db.start_processing(DOC_ID)
    db.mark_failed(DOC_ID, "File is not a valid PDF.")
    status, body = call_status(DOC_ID)
    assert status == 200
    assert body["status"] == "FAILED"
    assert body["error_message"] == "File is not a valid PDF."


def test_status_does_not_expose_internal_fields():
    add_record()
    _, body = call_status(DOC_ID)
    assert "s3_key" not in body and "expires_at" not in body and "content_type" not in body


@pytest.mark.parametrize("document_id", [str(uuid.uuid4()), "not-a-uuid", ""])
def test_unknown_or_malformed_ids_return_404(document_id):
    status, body = call_status(document_id)
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


def test_status_with_no_path_parameters_returns_404():
    response = status_handler.lambda_handler({"pathParameters": None}, None)
    assert response["statusCode"] == 404