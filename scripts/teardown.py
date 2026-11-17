"""Delete everything CloudDoc created in AWS.

Usage from the repo root:
    python scripts/teardown.py                        # delete the clouddoc-dev stack
    python scripts/teardown.py --include-sam-bucket   # also delete SAM's helper bucket and stack
"""
import argparse
import sys

import boto3
from botocore.exceptions import ClientError

REGION = "ap-southeast-2"
SAM_STACK = "aws-sam-cli-managed-default"


def bucket_names(cf, stack: str) -> list:
    try:
        resources = cf.list_stack_resources(StackName=stack)["StackResourceSummaries"]
    except ClientError:
        return []
    return [r["PhysicalResourceId"] for r in resources if r["ResourceType"] == "AWS::S3::Bucket"]


def empty_bucket(s3, name: str) -> None:
    bucket = s3.Bucket(name)
    try:
        bucket.object_versions.delete()  # also removes old versions in versioned buckets
        bucket.objects.all().delete()
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchBucket":
            raise
    print(f"  emptied bucket {name}")


def delete_stack(cf, stack: str) -> None:
    cf.delete_stack(StackName=stack)
    cf.get_waiter("stack_delete_complete").wait(
        StackName=stack, WaiterConfig={"Delay": 5, "MaxAttempts": 120}
    )
    print(f"  deleted stack {stack}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack", default="clouddoc-dev")
    parser.add_argument("--include-sam-bucket", action="store_true")
    args = parser.parse_args()

    session = boto3.Session(region_name=REGION)
    account = session.client("sts").get_caller_identity()["Account"]
    cf = session.client("cloudformation")
    s3 = session.resource("s3")

    print(f"Account {account}, region {REGION}")
    print(f"This will DELETE stack '{args.stack}': the API, functions, queues, table, bucket, and alarms.")
    if args.include_sam_bucket:
        print(f"It will also delete SAM's helper stack '{SAM_STACK}' and its bucket.")
    if input(f'Type "delete {args.stack}" to continue: ').strip() != f"delete {args.stack}":
        print("Cancelled.")
        return 1

    for name in bucket_names(cf, args.stack):
        empty_bucket(s3, name)
    delete_stack(cf, args.stack)

    if args.include_sam_bucket:
        for name in bucket_names(cf, SAM_STACK):
            empty_bucket(s3, name)
        delete_stack(cf, SAM_STACK)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())