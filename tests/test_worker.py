import json
from urllib.parse import quote_plus

import pytest
from botocore.exceptions import ClientError

from processor import document_worker
from services import dynamodb_service as db
from services import s3_service

pytestmark = pytest.mark.usefixtures("aws")

BUCKET = "clouddoc-test-bucket"
DOC_ID = "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10"
UPLOADED_AT = "2026-11-13T07:00:00Z"


def put_document(aws, filename, content, with_record=True):
    key = s3_service.build_object_key(DOC_ID, filename)
    aws.s3.put_object(Bucket=BUCKET, Key=key, Body=content)
    if with_record:
        db.create_document(
            document_id=DOC_ID, filename=filename,
            extension=filename.rsplit(".", 1)[-1],
            content_type="application/pdf" if filename.endswith(".pdf") else "text/plain",
            size_bytes=len(content), s3_key=key,
            uploaded_at=UPLOADED_AT, expires_at=1900000000,
        )
    return key


def exists(aws, key):
    try:
        aws.s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


def s3_record(key, event_name="ObjectCreated:Post"):
    return {
        "eventName": event_name,
        "s3": {"bucket": {"name": BUCKET}, "object": {"key": quote_plus(key, safe="/")}},
    }


def sqs_message(body, message_id="m-1"):
    if not isinstance(body, str):
        body = json.dumps(body)
    return {"messageId": message_id, "body": body}


def s3_message(key, message_id="m-1", event_name="ObjectCreated:Post"):
    return sqs_message({"Records": [s3_record(key, event_name)]}, message_id)


def run(*messages):
    return document_worker.lambda_handler({"Records": list(messages)}, None)


# ---- process_object ----

def test_valid_pdf_is_completed(aws, make_pdf):
    key = put_document(aws, "report.pdf", make_pdf(2))
    result = document_worker.process_object(BUCKET, key)
    assert result["status"] == "COMPLETED"

    item = db.get_document(DOC_ID)
    assert item["status"] == "COMPLETED"
    assert int(item["page_count"]) == 2
    assert item["uploaded_at"] == UPLOADED_AT      # original upload time is preserved
    assert item["processed_at"] > UPLOADED_AT
    assert "expires_at" not in item                # real documents never expire
    assert exists(aws, key)


def test_valid_txt_is_completed_without_page_count(aws):
    key = put_document(aws, "notes.txt", b"hello")
    assert document_worker.process_object(BUCKET, key)["status"] == "COMPLETED"
    item = db.get_document(DOC_ID)
    assert int(item["size_bytes"]) == 5
    assert "page_count" not in item


@pytest.mark.parametrize("content", [b"not a pdf at all", b"%PDF-1.4 garbage"])
def test_invalid_pdf_is_failed_and_file_deleted(aws, content):
    key = put_document(aws, "report.pdf", content)
    result = document_worker.process_object(BUCKET, key)
    assert result["status"] == "FAILED"

    item = db.get_document(DOC_ID)
    assert item["status"] == "FAILED"
    assert item["error_message"] == "File is not a valid PDF."
    assert not exists(aws, key)


def test_missing_file_marks_the_record_failed(aws):
    key = put_document(aws, "report.pdf", b"x")
    aws.s3.delete_object(Bucket=BUCKET, Key=key)
    assert document_worker.process_object(BUCKET, key)["status"] == "FAILED"
    assert db.get_document(DOC_ID)["error_message"] == "Uploaded file was not found."


def test_file_without_a_record_is_deleted(aws):
    key = put_document(aws, "report.pdf", b"x", with_record=False)
    assert document_worker.process_object(BUCKET, key)["status"] == "SKIPPED"
    assert not exists(aws, key)


def test_duplicate_delivery_after_completion_changes_nothing(aws, make_pdf):
    key = put_document(aws, "report.pdf", make_pdf())
    document_worker.process_object(BUCKET, key)
    first = db.get_document(DOC_ID)

    assert document_worker.process_object(BUCKET, key)["status"] == "SKIPPED"
    assert db.get_document(DOC_ID) == first
    assert exists(aws, key)


def test_duplicate_delivery_after_failure_finishes_the_delete(aws):
    key = put_document(aws, "report.pdf", b"not a pdf")
    document_worker.process_object(BUCKET, key)
    aws.s3.put_object(Bucket=BUCKET, Key=key, Body=b"leftover")  # a crash left the file behind

    assert document_worker.process_object(BUCKET, key)["status"] == "SKIPPED"
    assert not exists(aws, key)


def test_retry_after_a_crash_resumes_processing(aws, make_pdf):
    key = put_document(aws, "report.pdf", make_pdf())
    db.start_processing(DOC_ID)  # simulate a worker that died after starting
    assert document_worker.process_object(BUCKET, key)["status"] == "COMPLETED"
    assert db.get_document(DOC_ID)["status"] == "COMPLETED"


# ---- lambda_handler ----

def test_handler_decodes_url_encoded_keys(aws):
    key = put_document(aws, "my report.pdf", b"not a pdf")
    assert run(s3_message(key)) == {"batchItemFailures": []}
    assert db.get_document(DOC_ID)["status"] == "FAILED"
    assert not exists(aws, key)


def test_s3_test_event_is_ignored(aws):
    message = sqs_message({"Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": BUCKET})
    assert run(message) == {"batchItemFailures": []}


def test_non_create_events_are_ignored(aws):
    key = put_document(aws, "report.pdf", b"not a pdf")
    assert run(s3_message(key, event_name="ObjectRemoved:Delete")) == {"batchItemFailures": []}
    assert db.get_document(DOC_ID)["status"] == "PENDING"


@pytest.mark.parametrize("body", [
    "not json",
    "[1, 2]",
    json.dumps({"unexpected": "shape"}),
    json.dumps({"Records": [s3_record("junk")]}),
])
def test_poison_messages_are_reported_as_failures(aws, body):
    assert run(sqs_message(body)) == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}


def test_transient_error_keeps_the_file_and_allows_a_retry(aws, make_pdf, monkeypatch):
    key = put_document(aws, "report.pdf", make_pdf())
    real_get = s3_service.get_object_bytes
    calls = {"count": 0}

    def flaky_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:  # the first attempt hits a transient error
            raise ClientError(
                {"Error": {"Code": "InternalError", "Message": "try later"}}, "GetObject"
            )
        return real_get(*args, **kwargs)  # the retry works normally

    monkeypatch.setattr(s3_service, "get_object_bytes", flaky_once)

    assert run(s3_message(key)) == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
    assert exists(aws, key)
    assert db.get_document(DOC_ID)["status"] == "PROCESSING"

    assert run(s3_message(key)) == {"batchItemFailures": []}
    assert db.get_document(DOC_ID)["status"] == "COMPLETED"


def test_one_bad_message_does_not_block_the_batch(aws, make_pdf):
    key = put_document(aws, "report.pdf", make_pdf())
    result = run(sqs_message("not json", "m-1"), s3_message(key, "m-2"))
    assert result == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
    assert db.get_document(DOC_ID)["status"] == "COMPLETED"