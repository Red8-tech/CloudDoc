import pytest
from botocore.exceptions import ClientError

from services import dynamodb_service as db

pytestmark = pytest.mark.usefixtures("aws")

DOC_ID = "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10"


def new_record(**overrides):
    fields = dict(
        document_id=DOC_ID, filename="report.pdf", extension="pdf",
        content_type="application/pdf", size_bytes=2048,
        s3_key=f"uploads/{DOC_ID}/report.pdf",
        uploaded_at="2026-11-13T07:00:00Z", expires_at=1900000000,
    )
    fields.update(overrides)
    db.create_document(**fields)


def test_create_then_get():
    new_record()
    item = db.get_document(DOC_ID)
    assert item["status"] == "PENDING"
    assert item["filename"] == "report.pdf"
    assert int(item["expires_at"]) == 1900000000


def test_get_unknown_returns_none():
    assert db.get_document("nope") is None


def test_creating_the_same_id_twice_is_rejected():
    new_record()
    with pytest.raises(ClientError) as exc:
        new_record()
    assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


def test_start_processing_moves_to_processing_and_drops_ttl():
    new_record()
    outcome, record = db.start_processing(DOC_ID)
    assert outcome == db.STARTED
    assert record["uploaded_at"] == "2026-11-13T07:00:00Z"
    item = db.get_document(DOC_ID)
    assert item["status"] == "PROCESSING"
    assert "expires_at" not in item


def test_start_processing_can_be_retried_after_a_crash():
    new_record()
    assert db.start_processing(DOC_ID)[0] == db.STARTED
    assert db.start_processing(DOC_ID)[0] == db.STARTED


def test_start_processing_unknown_document():
    assert db.start_processing("nope") == (db.NOT_FOUND, None)


def test_start_processing_after_completion_is_refused():
    new_record()
    db.start_processing(DOC_ID)
    assert db.mark_completed(DOC_ID, 2048, 3) is True
    outcome, record = db.start_processing(DOC_ID)
    assert outcome == db.ALREADY_DONE
    assert record["status"] == "COMPLETED"


def test_mark_completed_stores_metadata():
    new_record()
    db.start_processing(DOC_ID)
    assert db.mark_completed(DOC_ID, 4096, 3) is True
    item = db.get_document(DOC_ID)
    assert item["status"] == "COMPLETED"
    assert int(item["size_bytes"]) == 4096
    assert int(item["page_count"]) == 3
    assert item["processed_at"].endswith("Z")


def test_mark_completed_without_page_count_leaves_it_out():
    new_record(filename="notes.txt", extension="txt")
    db.start_processing(DOC_ID)
    db.mark_completed(DOC_ID, 14, None)
    assert "page_count" not in db.get_document(DOC_ID)


def test_mark_completed_requires_processing():
    new_record()
    assert db.mark_completed(DOC_ID, 1, None) is False
    assert db.get_document(DOC_ID)["status"] == "PENDING"


def test_mark_failed_stores_the_error():
    new_record()
    db.start_processing(DOC_ID)
    assert db.mark_failed(DOC_ID, "File is not a valid PDF.") is True
    item = db.get_document(DOC_ID)
    assert item["status"] == "FAILED"
    assert item["error_message"] == "File is not a valid PDF."


def test_final_states_cannot_change():
    new_record()
    db.start_processing(DOC_ID)
    assert db.mark_failed(DOC_ID, "bad") is True
    assert db.mark_completed(DOC_ID, 1, None) is False
    assert db.mark_failed(DOC_ID, "again") is False
    assert db.get_document(DOC_ID)["status"] == "FAILED"