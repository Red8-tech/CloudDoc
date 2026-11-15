import io
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws
from pypdf import PdfWriter

from utils import config

BUCKET = "clouddoc-test-bucket"
TABLE = "clouddoc-test-documents"


def _build_pdf(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def make_pdf():
    return _build_pdf


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Fake credentials for every test, so nothing can reach real AWS."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture
def aws(monkeypatch):
    """One mocked AWS with the bucket and the documents table."""
    monkeypatch.setattr(config, "BUCKET_NAME", BUCKET)
    monkeypatch.setattr(config, "TABLE_NAME", TABLE)
    with mock_aws():
        s3 = boto3.client("s3", region_name=config.REGION)
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": config.REGION},
        )
        table = boto3.resource("dynamodb", region_name=config.REGION).create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "document_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "document_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield SimpleNamespace(s3=s3, table=table, bucket=BUCKET)