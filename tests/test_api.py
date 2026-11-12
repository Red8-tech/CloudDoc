import base64
import json
import uuid

import pytest

from api import status_handler, upload_handler
from utils import config

BUCKET = "clouddoc-test-bucket"


@pytest.fixture(autouse=True)
def bucket_name(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", BUCKET)


def valid_body(**overrides):
    body = {"filename": "report.pdf", "content_type": "application/pdf", "size_bytes": 2048}
    body.update(overrides)
    return body


def call_upload(body):
    if body is not None and not isinstance(body, str):
        body = json.dumps(body)
    response = upload_handler.lambda_handler({"body": body, "isBase64Encoded": False}, None)
    return response["statusCode"], json.loads(response["body"]), response


def test_upload_success_returns_a_form():
    status, body, response = call_upload(valid_body())
    assert status == 201
    assert response["headers"]["Content-Type"] == "application/json"
    assert uuid.UUID(body["document_id"]).version == 4
    assert body["status"] == "PENDING"
    assert body["expires_in"] == 300
    assert BUCKET in body["upload"]["url"]
    assert body["upload"]["fields"]["key"] == f"uploads/{body['document_id']}/report.pdf"
    assert body["upload"]["fields"]["Content-Type"] == "application/pdf"


def test_upload_success_for_txt():
    status, body, _ = call_upload(valid_body(filename="notes.txt", content_type="text/plain"))
    assert status == 201
    assert body["upload"]["fields"]["Content-Type"] == "text/plain"


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
def test_bad_requests_use_the_documented_error_shape(body, code):
    status, payload, _ = call_upload(body)
    assert status == 400
    assert payload["error"]["code"] == code
    assert payload["error"]["message"]


def test_unexpected_error_returns_generic_500(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(upload_handler.s3_service, "generate_upload_form", boom)
    status, payload, response = call_upload(valid_body())
    assert status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response["body"]


def test_missing_bucket_setting_returns_500(monkeypatch):
    monkeypatch.setattr(config, "BUCKET_NAME", "")
    status, payload, _ = call_upload(valid_body())
    assert status == 500
    assert payload["error"]["code"] == "INTERNAL_ERROR"


@pytest.mark.parametrize("path_parameters", [
    {"document_id": str(uuid.uuid4())},
    {"document_id": "not-a-uuid"},
    {"document_id": ""},
    {},
    None,
])
def test_status_returns_404_until_dynamodb_exists(path_parameters):
    response = status_handler.lambda_handler({"pathParameters": path_parameters}, None)
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error"]["code"] == "NOT_FOUND"