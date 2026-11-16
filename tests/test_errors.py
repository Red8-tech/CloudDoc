import base64
import json
from urllib.parse import quote_plus

import pytest
from botocore.exceptions import ClientError

from api import status_handler, upload_handler
from processor import document_worker
from services import dynamodb_service as db
from utils import config
from utils.responses import error_response
from utils.validators import ValidationError

pytestmark = pytest.mark.usefixtures("aws")

BUCKET = "clouddoc-test-bucket"
DOC_A = "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10"
DOC_B = "9a1c2d3e-4b5f-4a6b-8c7d-0e1f2a3b4c5d"
FAILURE = {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
SUCCESS = {"batchItemFailures": []}


def put_document(aws, doc_id, filename, content):
    key = f"uploads/{doc_id}/{filename}"
    aws.s3.put_object(Bucket=BUCKET, Key=key, Body=content)
    db.create_document(
        document_id=doc_id, filename=filename,
        extension=filename.rsplit(".", 1)[-1],
        content_type="application/pdf" if filename.endswith(".pdf") else "text/plain",
        size_bytes=len(content), s3_key=key,
        uploaded_at="2026-11-15T07:00:00Z", expires_at=1900000000,
    )
    return key


def s3_record(key):
    return {
        "eventName": "ObjectCreated:Post",
        "s3": {"bucket": {"name": BUCKET}, "object": {"key": quote_plus(key, safe="/")}},
    }


def run(body):
    message = {"messageId": "m-1", "body": json.dumps(body)}
    return document_worker.lambda_handler({"Records": [message]}, None)


def boom(*args, **kwargs):
    raise RuntimeError("secret internal detail")


# ---- responses and handlers ----

def test_unknown_error_code_defaults_to_500():
    assert error_response("SOMETHING_NEW", "x")["statusCode"] == 500


def test_status_returns_generic_500_when_dynamodb_fails(monkeypatch):
    monkeypatch.setattr(status_handler.dynamodb_service, "get_document", boom)
    response = status_handler.lambda_handler({"pathParameters": {"document_id": DOC_A}}, None)
    assert response["statusCode"] == 500
    assert json.loads(response["body"])["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response["body"]


def test_upload_rejects_a_body_that_is_not_valid_base64_json():
    event = {"body": "!!!", "isBase64Encoded": True}
    response = upload_handler.lambda_handler(event, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "INVALID_REQUEST"


# ---- DynamoDB service ----

def test_unexpected_dynamodb_errors_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(config, "TABLE_NAME", "no-such-table")
    with pytest.raises(ClientError) as exc:
        db.start_processing(DOC_A)
    assert exc.value.response["Error"]["Code"] == "ResourceNotFoundException"


# ---- worker ----

def test_one_message_with_two_documents_completes_both(aws, make_pdf):
    key_a = put_document(aws, DOC_A, "a.pdf", make_pdf())
    key_b = put_document(aws, DOC_B, "b.txt", b"hello")
    assert run({"Records": [s3_record(key_a), s3_record(key_b)]}) == SUCCESS
    assert db.get_document(DOC_A)["status"] == "COMPLETED"
    assert db.get_document(DOC_B)["status"] == "COMPLETED"


def test_partial_failure_in_a_message_is_safe_to_retry(aws, make_pdf):
    key = put_document(aws, DOC_A, "a.pdf", make_pdf())
    body = {"Records": [s3_record(key), s3_record("junk")]}

    assert run(body) == FAILURE                     # the malformed second record fails the message
    first = db.get_document(DOC_A)
    assert first["status"] == "COMPLETED"

    assert run(body) == FAILURE                     # SQS retries the whole message
    assert db.get_document(DOC_A) == first          # the good document is untouched, not reprocessed


def test_non_ascii_filename_round_trip(aws, make_pdf):
    key = put_document(aws, DOC_A, "résumé.pdf", make_pdf())
    assert run({"Records": [s3_record(key)]}) == SUCCESS
    assert db.get_document(DOC_A)["status"] == "COMPLETED"


@pytest.mark.parametrize("body", [
    "abc",                                         # invalid base64 padding
    base64.b64encode(b"\xff\xfe\xfd").decode(),    # valid base64, but not valid UTF-8
])
def test_upload_rejects_undecodable_base64_bodies(body):
    response = upload_handler.lambda_handler({"body": body, "isBase64Encoded": True}, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error"]["code"] == "INVALID_REQUEST"


def test_finalizing_errors_other_than_a_lost_race_are_not_swallowed(monkeypatch):
    monkeypatch.setattr(config, "TABLE_NAME", "no-such-table")
    with pytest.raises(ClientError) as exc:
        db.mark_completed(DOC_A, 1, None)
    assert exc.value.response["Error"]["Code"] == "ResourceNotFoundException"


def test_losing_a_race_on_completion_changes_nothing(aws, make_pdf, monkeypatch):
    key = put_document(aws, DOC_A, "a.pdf", make_pdf())
    real_extract = document_worker.extract_metadata

    def other_worker_finishes_first(*args, **kwargs):
        db.mark_completed(DOC_A, 1, 99)     # another worker completes while we are busy
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(document_worker, "extract_metadata", other_worker_finishes_first)
    assert document_worker.process_object(BUCKET, key)["status"] == "SKIPPED"
    assert int(db.get_document(DOC_A)["page_count"]) == 99   # the other worker's result stands


def test_losing_a_race_on_failure_keeps_the_file(aws, monkeypatch):
    key = put_document(aws, DOC_A, "a.pdf", b"not a pdf")

    def other_worker_finishes_first(*args, **kwargs):
        db.mark_completed(DOC_A, 9, 1)      # the document actually completed elsewhere
        raise ValidationError("INVALID_FILE_TYPE", "File is not a valid PDF.")

    monkeypatch.setattr(document_worker, "extract_metadata", other_worker_finishes_first)
    assert document_worker.process_object(BUCKET, key)["status"] == "SKIPPED"
    assert db.get_document(DOC_A)["status"] == "COMPLETED"
    aws.s3.head_object(Bucket=BUCKET, Key=key)   # raises if the file was deleted