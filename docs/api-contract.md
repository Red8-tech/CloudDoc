# CloudDoc: API Contract

Base URL: `https://{api-id}.execute-api.ap-southeast-2.amazonaws.com/{stage}`
All requests and responses use JSON, except the file upload itself.

## 1. Create a document and get an upload URL

`POST /documents`

Request body:

```json
{
  "filename": "report.pdf",
  "content_type": "application/pdf",
  "size_bytes": 204800
}
```

Rules:
- `filename`: required, 1 to 255 characters, extension must be `.pdf` or `.txt`.
- `content_type`: required, must be `application/pdf` or `text/plain`.
- `size_bytes`: required, integer, 1 to 10485760 (10 MB).

Success: `201 Created`

```json
{
  "document_id": "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10",
  "status": "PENDING",
  "upload": {
    "url": "https://{bucket}.s3.ap-southeast-2.amazonaws.com/",
    "fields": { "key": "...", "Content-Type": "...", "policy": "...", "x-amz-signature": "..." }
  },
  "expires_in": 300
}
```

Errors: `400` (invalid body or unsupported type or size), `500` (unexpected error).

## 2. Upload the file to S3

This call goes directly to S3, not to the API. Send a multipart form containing
every key from `upload.fields`, followed by the `file` field **last**.

```powershell
curl.exe -X POST "<upload.url>" -F "key=<...>" -F "Content-Type=<...>" -F "policy=<...>" -F "x-amz-signature=<...>" -F "file=@report.pdf"
```

S3 returns `204` on success. S3 rejects files above 10 MB or with a mismatched
content type before they are stored. The worker validates again after upload.

## 3. Get document status

`GET /documents/{document_id}`

Success: `200 OK`

```json
{
  "document_id": "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10",
  "status": "COMPLETED",
  "filename": "report.pdf",
  "extension": "pdf",
  "size_bytes": 204800,
  "page_count": 12,
  "uploaded_at": "2026-11-07T10:15:30Z",
  "processed_at": "2026-11-07T10:15:34Z",
  "error_message": null
}
```

Notes:
- `page_count` is `null` for TXT files.
- `error_message` is set only when `status` is `FAILED`.
- Timestamps are ISO 8601, UTC.

Errors: `404` (unknown document ID), `500`.

## 4. Error format

Every error uses the same shape:

```json
{ "error": { "code": "INVALID_FILE_TYPE", "message": "Only PDF and TXT files are supported." } }
```

| HTTP | Code | Meaning |
|------|------|---------|
| 400 | `INVALID_REQUEST` | Missing or malformed field |
| 400 | `INVALID_FILE_TYPE` | Extension or content type not allowed |
| 400 | `FILE_TOO_LARGE` | `size_bytes` above the limit |
| 404 | `NOT_FOUND` | No document with that ID |
| 500 | `INTERNAL_ERROR` | Unexpected failure (details only in CloudWatch) |

## 5. Status values

| Status | Meaning |
|--------|---------|
| `PENDING` | Record created; file not yet processed |
| `PROCESSING` | Worker has picked up the job |
| `COMPLETED` | Validated and metadata extracted |
| `FAILED` | Validation or processing failed; see `error_message` |

## 6. Future (not part of the MVP)

### List and filter documents

`GET /documents`

Query parameters (all optional):

| Parameter | Description |
|-----------|-------------|
| `status` | Return only documents with this status (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`) |
| `limit` | Page size, 1 to 100, default 20 |
| `next_token` | Opaque token from a previous response, used to fetch the next page |

Example: `GET /documents?status=FAILED&limit=10`

Success: `200 OK`

```json
{
  "items": [
    {
      "document_id": "3f2b8c1e-5a47-4d0e-9c1b-7a9d2e6f4b10",
      "status": "FAILED",
      "filename": "scan.pdf",
      "extension": "pdf",
      "size_bytes": 512000,
      "uploaded_at": "2026-11-07T10:15:30Z",
      "error_message": "File is not a valid PDF."
    }
  ],
  "next_token": "eyJkb2N1bWVudF9pZCI6Ij..."
}
```

Notes:
- Results are sorted by `uploaded_at`, newest first.
- `next_token` is `null` on the last page.
- Errors: `400` (invalid `status` or `limit`), `500`.
- Implementation plan: a DynamoDB global secondary index on `status` and `uploaded_at`,
  queried instead of scanning the table.

### Other candidates

- `GET /documents?sha256={hash}` to find duplicates, once duplicate detection exists.
- `DELETE /documents/{document_id}` to remove a document and its file.