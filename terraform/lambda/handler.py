"""Prove both halves of the control from inside the private subnet.

1. Reaching huggingface.co must FAIL -- there is no route to the internet.
2. Reading the mirrored model from S3 must SUCCEED -- via the gateway
   endpoint, and the bytes must match the manifest recorded at approval.

Together those show that an inference workload here can only load models that
went through the gate, and cannot quietly fall back to the public Hub.
"""

import hashlib
import json
import os
import time
import socket
import urllib.request

import boto3

BUCKET = os.environ["MIRROR_BUCKET"]
REPO = os.environ["MODEL_REPO"]

# Short, so a blackholed route fails fast instead of burning the timeout.
PROBE_TIMEOUT = 3
PROBES = [
    "https://huggingface.co/api/models/sentence-transformers/all-MiniLM-L6-v2",
    "https://cdn-lfs.huggingface.co/",
    "https://pypi.org/simple/",
]

s3 = boto3.client("s3")


def probe(url):
    """Try to reach the public internet. Expected to fail."""
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as r:
            return {"url": url, "reached": True, "status": r.status}
    except Exception as exc:
        return {"url": url, "reached": False, "error": f"{type(exc).__name__}: {exc}"}


def newest_revision():
    prefix = f"models/{REPO}/"
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=BUCKET, Prefix=prefix, Delimiter="/"
    )
    revs = [
        cp["Prefix"].rstrip("/").rsplit("/", 1)[-1]
        for page in pages
        for cp in page.get("CommonPrefixes", [])
    ]
    if not revs:
        raise RuntimeError(f"nothing mirrored under s3://{BUCKET}/{prefix}")
    return sorted(revs)[-1]


def verify_from_mirror():
    """Read the model from S3 and check it against the approved manifest."""
    revision = newest_revision()
    prefix = f"models/{REPO}/{revision}"
    manifest = json.loads(
        s3.get_object(Bucket=BUCKET, Key=f"{prefix}/_manifest.json")["Body"].read()
    )

    checked, mismatched, total = 0, [], 0
    for entry in manifest["files"]:
        body = s3.get_object(Bucket=BUCKET, Key=f"{prefix}/{entry['path']}")["Body"]
        digest = hashlib.sha256()
        while chunk := body.read(1 << 20):
            digest.update(chunk)
        checked += 1
        total += entry["bytes"]
        if digest.hexdigest() != entry["sha256"]:
            mismatched.append(entry["path"])

    return {
        "revision": revision,
        "approved_at": manifest["mirrored_at"],
        "verdict_at_approval": manifest["verdict"],
        "pickle_files_excluded": len(manifest.get("pickle_files_left_behind", [])),
        "files_checked": checked,
        "bytes": total,
        "mismatched": mismatched,
        "integrity_ok": not mismatched,
    }


def lambda_handler(event, context):
    hostname = socket.gethostname()

    t0 = time.monotonic()
    internet = [probe(u) for u in PROBES]
    probe_secs = round(time.monotonic() - t0, 1)

    t1 = time.monotonic()
    mirror = verify_from_mirror()
    mirror_secs = round(time.monotonic() - t1, 1)

    blocked = all(not p["reached"] for p in internet)
    result = {
        "running_in": hostname,
        "internet_reachable": not blocked,
        "probes": internet,
        "mirror": mirror,
        "seconds": {"internet_probes": probe_secs, "mirror_verify": mirror_secs},
        "control_holds": blocked and mirror["integrity_ok"],
    }
    print(json.dumps(result, indent=2))
    return result
