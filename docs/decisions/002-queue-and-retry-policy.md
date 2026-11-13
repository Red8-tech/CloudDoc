# ADR 002: Queue, retries, and failure handling

Status: accepted

## Decisions

1. Standard SQS queue between S3 and the worker, with a dead-letter queue
   after 3 receives, kept 14 days.
2. Visibility timeout of 180 seconds, 6x the worker timeout.
3. Partial batch responses, so one bad message does not retry the batch.
4. Permanent validation failures delete the S3 file and are not retried.
   Transient errors are retried and never delete the file.
5. Worker concurrency capped at 2 to bound cost under a flood of uploads.
6. The worker role has s3:ListBucket on the uploads/ prefix so a missing
   object returns 404 (safe to skip) rather than 403 (looks like a fault).

## Consequences

Retries take minutes, not seconds, and standard queues deliver at least once,
so the worker tolerates duplicates. DynamoDB conditional writes (Week 6) make
that guarantee explicit.