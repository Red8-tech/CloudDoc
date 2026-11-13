import json
from urllib.parse import quote_plus

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from processor import document_worker
from services import s3_service
from utils import config

BUCKET = "clouddoc-test-bucket"
DOC_ID = "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10"


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=config.REGION)
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": config.REGION},
        )
        yield client


def put(s3, filename, content):
    key = s3_service.build_object_key(DOC_ID, filename)
    s3.put_object(Bucket=BUCKET, Key=key, Body=content)
    return key


def exists(s3, key):
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
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

def test_valid_pdf_is_completed_and_kept(s3, make_pdf):
    key = put(s3, "report.pdf", make_pdf(2))
    result = document_worker.process_object(BUCKET, key)
    assert result["status"] == "COMPLETED"
    assert result["metadata"]["page_count"] == 2
    assert exists(s3, key)


def test_valid_txt_is_completed(s3):
    key = put(s3, "notes.txt", b"hello")
    result = document_worker.process_object(BUCKET, key)
    assert result["status"] == "COMPLETED"
    assert result["metadata"]["page_count"] is None


@pytest.mark.parametrize("content", [b"not a pdf at all", b"%PDF-1.4 garbage"])
def test_invalid_pdf_fails_and_file_is_deleted(s3, content):
    key = put(s3, "report.pdf", content)
    result = document_worker.process_object(BUCKET, key)
    assert result["status"] == "FAILED"
    assert result["error_code"] == "INVALID_FILE_TYPE"
    assert not exists(s3, key)


def test_missing_object_is_skipped(s3):
    key = s3_service.build_object_key(DOC_ID, "gone.pdf")
    assert document_worker.process_object(BUCKET, key)["status"] == "SKIPPED"


# ---- lambda_handler ----

def test_handler_decodes_url_encoded_keys(s3):
    # The fake PDF is deleted only if the worker found it via the decoded key.
    key = put(s3, "my report.pdf", b"not a pdf")
    assert run(s3_message(key)) == {"batchItemFailures": []}
    assert not exists(s3, key)


def test_s3_test_event_is_ignored(s3):
    message = sqs_message({"Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": BUCKET})
    assert run(message) == {"batchItemFailures": []}


def test_non_create_events_are_ignored(s3):
    key = put(s3, "report.pdf", b"not a pdf")
    assert run(s3_message(key, event_name="ObjectRemoved:Delete")) == {"batchItemFailures": []}
    assert exists(s3, key)  # untouched


@pytest.mark.parametrize("body", [
    "not json",
    "[1, 2]",
    json.dumps({"unexpected": "shape"}),
    json.dumps({"Records": [s3_record("junk")]}),
])
def test_poison_messages_are_reported_as_failures(s3, body):
    assert run(sqs_message(body)) == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}


def test_transient_error_reports_failure_and_keeps_file(s3, make_pdf, monkeypatch):
    key = put(s3, "report.pdf", make_pdf())

    def flaky(*args, **kwargs):
        raise ClientError({"Error": {"Code": "InternalError", "Message": "try later"}}, "GetObject")

    monkeypatch.setattr(s3_service, "get_object_bytes", flaky)
    assert run(s3_message(key)) == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}
    assert exists(s3, key)


def test_one_bad_message_does_not_block_the_batch(s3, make_pdf):
    key = put(s3, "report.pdf", make_pdf())
    result = run(sqs_message("not json", "m-1"), s3_message(key, "m-2"))
    assert result == {"batchItemFailures": [{"itemIdentifier": "m-1"}]}


def test_duplicate_delivery_is_safe(s3, make_pdf):
    good = put(s3, "report.pdf", make_pdf())
    assert run(s3_message(good)) == {"batchItemFailures": []}
    assert run(s3_message(good)) == {"batchItemFailures": []}
    assert exists(s3, good)

    bad = put(s3, "fake.pdf", b"not a pdf")
    assert run(s3_message(bad)) == {"batchItemFailures": []}
    assert run(s3_message(bad)) == {"batchItemFailures": []}  # second time: already gone
    assert not exists(s3, bad)