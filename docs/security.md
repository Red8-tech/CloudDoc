# CloudDoc: Security

## Controls

| Area | Control |
|------|---------|
| Data at rest | S3 SSE-S3 encryption, DynamoDB encryption (default), SQS managed encryption |
| Data in transit | HTTPS only; the bucket policy denies any request without TLS |
| Public access | S3 Block Public Access enabled (all four settings) |
| Uploads | Presigned POST valid for 5 minutes; S3 enforces content type and size range; the worker validates the real bytes again |
| Identity | No long-lived keys; Lambda uses role credentials; local CLI uses a temporary login |
| API abuse | Throttle of 5 requests/second (burst 10) per route; worker concurrency capped at 2 |
| Errors | Clients get generic 500 messages; details go only to CloudWatch; internal fields (s3_key, expires_at) are never returned |
| Secrets | None in the repo; samconfig.toml is git-ignored |
| Data lifecycle | Abandoned PENDING records expire after 24 hours; failed files are deleted; incomplete multipart uploads are aborted after 1 day |
| Monitoring | JSON logs kept 14 days; alarms on the DLQ, worker errors, and API 5xx |

## IAM: least privilege per function

| Function | Allowed | Why |
|----------|---------|-----|
| Upload | s3:PutObject on uploads/*; dynamodb:PutItem | Signs the upload form and creates the record |
| Status | dynamodb:GetItem | Reads one record |
| Worker | s3:GetObject, s3:DeleteObject on uploads/*; s3:ListBucket for uploads/*; dynamodb:GetItem, UpdateItem | Reads the file, deletes bad files, updates status |

No function can scan or delete table items, list other prefixes, or write
outside uploads/. SAM also attaches the standard CloudWatch Logs and SQS
execution permissions.

## Known limitations

- No authentication: the API is public, protected only by throttling. Next step: an API key, Cognito, or a Lambda authorizer.
- No WAF, for cost reasons.
- No malware scanning of uploaded files.
- A message that exhausts its retries leaves its record in PROCESSING until an operator acts (see runbook.md).
- No DynamoDB point-in-time recovery and no S3 versioning (acceptable for a learning project).
- The alert topic is unencrypted, because CloudWatch alarms cannot publish to topics using the AWS-managed SNS key.

## Pre-deploy review checklist

- [ ] No new wildcard (*) actions or resources in IAM statements
- [ ] No secrets, keys, or account-specific values committed
- [ ] New endpoints validate input and return the standard error shape
- [ ] New resources are encrypted and have a deletion plan