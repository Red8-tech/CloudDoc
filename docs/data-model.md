# CloudDoc: Data Model

## 1. Access patterns

DynamoDB tables are designed around the queries we need, so these come first.

| # | Question | Used by | Phase |
|---|----------|---------|-------|
| AP1 | Create a record when an upload is requested | `POST /documents` | MVP |
| AP2 | Get one document by ID | `GET /documents/{id}` | MVP |
| AP3 | Update status and metadata after processing | Worker | MVP |
| AP4 | List documents by status, newest first | `GET /documents?status=` | Advanced |
| AP5 | Find a document by content hash (duplicates) | Worker | Advanced |

## 2. Table: `clouddoc-documents`

| Setting | Value |
|---------|-------|
| Partition key | `document_id` (String, UUID v4) |
| Sort key | none |
| Billing mode | On-demand (pay per request, nothing when idle) |
| TTL attribute | `expires_at` (Number, epoch seconds), enabled later |

A partition key alone is enough for AP1 to AP3 because each document is read and written by its ID.

## 3. Attributes

| Attribute | Type | Set by | Notes |
|-----------|------|--------|-------|
| `document_id` | String | API handler | Primary key |
| `status` | String | API handler, worker | PENDING, PROCESSING, COMPLETED, FAILED |
| `filename` | String | API handler | Original name from the request |
| `extension` | String | API handler | `pdf` or `txt`, lowercase |
| `content_type` | String | API handler | `application/pdf` or `text/plain` |
| `size_bytes` | Number | API handler | Declared size, replaced by the real size in the worker |
| `s3_key` | String | API handler | `uploads/{document_id}/{filename}` |
| `uploaded_at` | String | API handler | ISO 8601, UTC. Time the record was created |
| `page_count` | Number | Worker | Absent for TXT |
| `processed_at` | String | Worker | ISO 8601, UTC |
| `error_message` | String | Worker | Only when FAILED |
| `sha256` | String | Worker | Advanced phase |
| `expires_at` | Number | API handler | Epoch seconds, `uploaded_at` + 24h; removed by the worker when processing starts |

## 4. Global secondary indexes

| Index | Keys | Serves | Phase |
|-------|------|--------|-------|
| `status-uploaded_at-index` | `status` (PK), `uploaded_at` (SK) | AP4 | Advanced |
| `sha256-index` | `sha256` (PK) | AP5 | Advanced |

The MVP table has no indexes. We add them when the advanced features arrive.

## 5. Status lifecycle

```
PENDING -> PROCESSING -> COMPLETED
                      -> FAILED
```

| Transition | Who | Condition (DynamoDB conditional write) |
|------------|-----|-----------------------------------------|
| (new) -> PENDING | API handler | `attribute_not_exists(document_id)` |
| PENDING -> PROCESSING | Worker | `status = PENDING` |
| PROCESSING -> COMPLETED | Worker | `status = PROCESSING` |
| PROCESSING -> FAILED | Worker | `status = PROCESSING` |

Conditions make the worker idempotent. If SQS delivers the same message twice,
the second attempt fails the `status = PENDING` check and the worker stops
instead of processing the file again.

## 6. S3 layout

- Bucket: private, public access blocked, encryption on, name `clouddoc-uploads-{account-id}`.
- Key: `uploads/{document_id}/{filename}`.
- The worker finds the record from the `document_id` embedded in the key.

## 7. Open decisions

- **TTL for abandoned PENDING records: 24 hours.** `expires_at` is set to
  `uploaded_at + 24h` when the record is created. DynamoDB deletes expired
  records automatically. The worker removes the TTL attribute when it moves a
  record to PROCESSING, so real documents are never deleted by it.
- **FAILED documents: the S3 file is deleted.** The record stays in DynamoDB
  with `status = FAILED` and an `error_message`, so the client can still see
  what went wrong.
- Deletion happens only for permanent validation failures. Transient errors
  are retried by SQS and never delete the file.