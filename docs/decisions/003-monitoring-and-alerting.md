# ADR 003: Monitoring and alerting

Status: accepted

## Decisions

1. Alarm on the dead-letter queue, not only on Lambda errors. The worker reports
   per-message failures through batchItemFailures, so Lambda's Errors metric
   misses them.
2. Alarm on API Gateway 5xx, because the handlers return 500 responses
   instead of raising.
3. Email notifications are optional (a template parameter kept in the
   git-ignored samconfig.toml), so the repository holds no personal data.
4. Operators handle DLQ messages manually, with a written runbook. Auto-draining
   the DLQ with a consumer would hide failures and remove the alarm signal.
5. CI runs tests and template linting without any AWS credentials.

## Consequences

A failed job needs a person to act, but nothing fails silently. The
PROCESSING-after-DLQ gap is documented and has a defined fix.