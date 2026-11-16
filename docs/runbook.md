# CloudDoc: Runbook

Set these first:

```powershell
$queueUrl = "https://sqs.ap-southeast-2.amazonaws.com/<account-id>/clouddoc-documents-dev"
$dlqUrl = "https://sqs.ap-southeast-2.amazonaws.com/<account-id>/clouddoc-documents-dlq-dev"
```

## Alarm: clouddoc-dlq-not-empty-dev

A message failed all 3 attempts.

1. Read the message (it stays hidden for 30 seconds, then returns):
   `aws sqs receive-message --queue-url $dlqUrl --max-number-of-messages 5`
2. Find out why: `aws logs tail /aws/lambda/clouddoc-worker-dev --since 1h --filter-pattern "Failed to process"`
3. Decide:
   - Malformed or irrelevant message: purge it with `aws sqs purge-queue --queue-url $dlqUrl`.
   - A real document hit a bug: fix and deploy the bug, then move the messages back with
     `aws sqs start-message-move-task --source-arn <dlq-arn>`. The worker resumes
     PROCESSING records, so a retry is safe.
4. The document record may still say PROCESSING. If you will not retry it, mark it failed from the repo root:

```powershell
$env:PYTHONPATH = "src"; $env:TABLE_NAME = "clouddoc-documents-dev"
python -c "from services import dynamodb_service as db; print(db.mark_failed('<document_id>', 'Processing failed after several attempts.'))"
```

   It prints `True` when the record was PROCESSING and is now FAILED.

## Alarm: clouddoc-worker-errors-dev

The worker crashed or timed out (per-message failures show up in the DLQ alarm instead).
Check the worker logs for a traceback or a "Task timed out" line. Timeouts on large PDFs
mean the 30-second timeout or 512 MB memory needs raising.

## Alarm: clouddoc-api-5xx-dev

The API returned a server error. Check `/aws/lambda/clouddoc-upload-dev` and
`/aws/lambda/clouddoc-status-dev` for "Unexpected error". Common causes: a missing
permission after a template change, or DynamoDB being unavailable.

## Records stuck in PENDING

A PENDING record means the file was never uploaded. DynamoDB deletes it about
24 to 72 hours after creation, so no action is needed.