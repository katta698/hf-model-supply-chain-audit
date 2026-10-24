"""Delete everything this project created in AWS.

Ships alongside the create path, not after it. The bucket is versioned, so
deleting objects is not enough -- every version and delete marker has to go or
the bucket will refuse to be removed and will keep billing for storage.

Usage:
    python scripts/teardown.py --bucket my-mirror --dry-run
    python scripts/teardown.py --bucket my-mirror --yes
"""

import argparse
import sys

import boto3
from botocore.exceptions import ClientError


def all_versions(s3, bucket):
    """Every object version and delete marker in the bucket."""
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket):
        for key in ("Versions", "DeleteMarkers"):
            for item in page.get(key, []):
                yield {"Key": item["Key"], "VersionId": item["VersionId"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="required to actually delete")
    args = ap.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    try:
        s3.head_bucket(Bucket=args.bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            print(f"{args.bucket} does not exist; nothing to do.")
            return 0
        raise

    versions = list(all_versions(s3, args.bucket))
    size = sum(
        obj["Size"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=args.bucket)
        for obj in page.get("Contents", [])
    )
    print(f"bucket   {args.bucket}")
    print(f"contents {len(versions)} object versions, {size / 1e6:.1f} MB current")

    if args.dry_run or not args.yes:
        print("\ndry run. Re-run with --yes to delete the bucket and all versions.")
        return 0

    for i in range(0, len(versions), 1000):  # delete_objects caps at 1000
        batch = versions[i : i + 1000]
        s3.delete_objects(Bucket=args.bucket, Delete={"Objects": batch, "Quiet": True})
        print(f"  deleted {i + len(batch)}/{len(versions)} versions")

    s3.delete_bucket(Bucket=args.bucket)
    print(f"\ndeleted bucket {args.bucket}. Nothing left billing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
