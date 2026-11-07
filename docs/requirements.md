# CloudDoc: Requirements

## 1. Goal

Organizations receive hundreds of documents every day, and manually uploading,
validating, organizing, and tracking them takes time. CloudDoc automates this
with AWS serverless services: users upload a document through an API, and the
system validates it, extracts metadata, and tracks its processing status.

## 2. Functional requirements

| ID  | Requirement |
|-----|-------------|
| FR1 | A client can request an upload through an API and receives a unique document ID. |
| FR2 | Documents are stored in a private Amazon S3 bucket. |
| FR3 | A completed upload automatically triggers processing, with no manual step. |
| FR4 | The system validates file type (PDF or TXT) and size (maximum 10 MB). |
| FR5 | The system extracts metadata: filename, extension, size, upload time, and page count for PDFs. |
| FR6 | Processing jobs pass through an SQS queue. |
| FR7 | Each document has a status: PENDING, PROCESSING, COMPLETED, or FAILED. |
| FR8 | A client can retrieve a document's status and metadata through an API. |

## 3. Non-functional requirements

- Security: the S3 bucket blocks all public access; upload URLs expire in 5 minutes;
  each Lambda has its own least-privilege IAM role.
- Reliability: processing is idempotent, because SQS can deliver a message more than once.
- Observability: every Lambda writes structured logs to CloudWatch.
- Cost: the whole system runs within the AWS Free plan credits and can be deleted
  with one command.
- Quality: validation and processing logic is covered by automated tests.
- Error handling: API returns errors in one consistent JSON shape

## 4. Constraints and rules

- Allowed types for MVP: PDF and TXT.
- Maximum size: 10 MB .
- Region: ap-southeast-2.
- Runtime: Python 3.12.
- Infrastructure defined with AWS SAM.

## 5. Out of scope for MVP

DOCX support, user authentication, a web UI, search and filtering,
duplicate detection (planned for the advanced phase).

## 6. Status lifecycle

PENDING -> PROCESSING -> COMPLETED
                      -> FAILED

PENDING means the record exists but the file is not yet uploaded or processed.