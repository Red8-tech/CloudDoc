import base64
import json
from datetime import datetime, timezone

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

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


def decode_policy(form: dict) -> dict:
    return json.loads(base64.b64decode(form["fields"]["policy"]))


def test_build_object_key():
    assert s3_service.build_object_key(DOC_ID, "report.pdf") == f"uploads/{DOC_ID}/report.pdf"


def test_document_id_round_trip():
    key = s3_service.build_object_key(DOC_ID, "my report.pdf")
    assert s3_service.document_id_from_key(key) == DOC_ID


@pytest.mark.parametrize("key", ["", "report.pdf", "uploads/", "uploads/abc", "other/abc/report.pdf"])
def test_document_id_from_bad_key(key):
    with pytest.raises(ValueError):
        s3_service.document_id_from_key(key)


def test_upload_form_targets_the_bucket_and_key(s3):
    form = s3_service.generate_upload_form(BUCKET, DOC_ID, "report.pdf", "application/pdf")
    assert BUCKET in form["url"]
    assert form["key"] == f"uploads/{DOC_ID}/report.pdf"
    assert form["fields"]["key"] == form["key"]
    assert form["fields"]["Content-Type"] == "application/pdf"


def test_upload_policy_enforces_type_and_size(s3):
    form = s3_service.generate_upload_form(BUCKET, DOC_ID, "report.pdf", "application/pdf")
    conditions = decode_policy(form)["conditions"]
    assert {"bucket": BUCKET} in conditions
    assert {"key": form["key"]} in conditions
    assert {"Content-Type": "application/pdf"} in conditions
    assert ["content-length-range", 1, config.MAX_FILE_SIZE_BYTES] in conditions


def test_upload_policy_expires_in_five_minutes(s3):
    form = s3_service.generate_upload_form(BUCKET, DOC_ID, "notes.txt", "text/plain")
    expiration = datetime.strptime(
        decode_policy(form)["expiration"], "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    seconds_left = (expiration - datetime.now(timezone.utc)).total_seconds()
    assert 0 < seconds_left <= config.UPLOAD_URL_EXPIRY_SECONDS + 5


def test_get_and_delete_object(s3):
    key = s3_service.build_object_key(DOC_ID, "notes.txt")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"hello")

    assert s3_service.get_object_bytes(BUCKET, key) == b"hello"

    s3_service.delete_object(BUCKET, key)
    with pytest.raises(ClientError) as exc:
        s3_service.get_object_bytes(BUCKET, key)
    assert exc.value.response["Error"]["Code"] == "NoSuchKey"