# ADR 001: Core architecture choices

Status: accepted
Date: 2026-11-07

## Context

CloudDoc must accept documents, validate them, extract metadata, and track
status, using AWS serverless services within free-plan limits.

## Decisions

1. **AWS SAM for infrastructure.** One `template.yaml` defines every resource,
   so the system deploys and deletes with single commands.
2. **Presigned POST for uploads.** Files go straight to S3, and S3 enforces the
   size limit and content type before storing anything. API Gateway never
   carries file bytes.
3. **S3 -> SQS -> Lambda for processing.** The queue absorbs bursts, enables
   retries, and sends repeatedly failing jobs to a dead-letter queue.
4. **DynamoDB with on-demand billing.** Access is by document ID, so a simple
   key design is enough, and an idle table costs almost nothing.
5. **Idempotent worker via conditional writes.** SQS delivers at least once, so
   status transitions only succeed from the expected previous status.
6. **TTL for abandoned uploads.** PENDING records expire after 24 hours.
7. **Delete the S3 file only on permanent validation failure.** Transient
   errors are retried.

## Consequences

- More moving parts than a direct S3 -> Lambda trigger.
- Safer under load, easy to test piece by piece, and each choice can be
  explained and defended.
- Tests use `moto` to mock AWS, so they never touch a real account.