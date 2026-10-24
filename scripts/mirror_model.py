"""Mirror an approved model revision from the Hub into S3.

This is the gate. Production never fetches from huggingface.co; it reads only
what this script has already approved and copied. Same pattern as mirroring a
container image into ECR instead of letting prod pull from Docker Hub.

What it does:

  1. Resolves the model to a specific commit SHA -- never a floating ref.
  2. Audits that exact revision (weight format, auto_map, licence, gating).
  3. Refuses to mirror anything that fails policy.
  4. Downloads only what is needed to serve, chosen by allowlist. Pickle
     duplicates, stray weight formats and training scripts are simply absent
     from the mirror, so a consumer cannot load them even by accident.
  5. Uploads under a SHA-addressed prefix, so a given path is immutable.
  6. Writes a manifest recording what was approved, when, by whom, and the
     sha256 of every mirrored file.

Usage:
    python scripts/mirror_model.py sentence-transformers/all-MiniLM-L6-v2 \
        --bucket my-model-mirror --create-bucket
    python scripts/mirror_model.py some/model --dry-run
"""

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import pathlib
import sys

import boto3
from botocore.exceptions import ClientError
from huggingface_hub import HfApi, snapshot_download
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from inspect_model import PICKLE_SUFFIXES, remote_code  # noqa: E402

from license_policy import classify  # noqa: E402

api = HfApi()

# Allowlist, not denylist. A denylist of "unsafe extensions" leaks in both
# directions: it waves through formats nobody thought of (rust_model.ot), and
# excluding one file of a multi-file artifact leaves a broken remainder
# (openvino .xml without its .bin). Mirror only what is needed to serve.
METADATA = ("*.json", "*.txt", "*.md", "*.model")  # configs, tokenizers, cards
WEIGHTS = {
    "safetensors": ("*.safetensors",),
    "onnx": ("onnx/*.onnx", "onnx/*.onnx_data"),
    "openvino": ("openvino/*.xml", "openvino/*.bin"),
}


def audit(repo_id, revision=None):
    """Audit one revision. Returns (info, findings) or raises."""
    info = api.model_info(repo_id, revision=revision, files_metadata=True)

    pickles, safetensors = [], []
    for f in info.siblings:
        if f.rfilename.endswith(PICKLE_SUFFIXES):
            pickles.append(f.rfilename)
        elif f.rfilename.endswith(".safetensors"):
            safetensors.append(f.rfilename)

    code = remote_code(repo_id, info)
    raw_license = (info.card_data or {}).get("license") or None

    return info, {
        "revision": info.sha,
        "license": raw_license,
        "license_bucket": classify(raw_license),
        "pickle_files": pickles,
        "safetensors_files": safetensors,
        "pickle_only": bool(pickles) and not safetensors,
        "remote_code": code,
        "remote_code_external": [t for t in code if "--" in t],
        "gated": info.gated or False,
    }


def decide(f):
    """Return (verdict, blocking, needs_human).

    BLOCK is for things configuration cannot mitigate. REVIEW is for things a
    person must decide. Mirroring proceeds only on PASS, or on REVIEW with an
    explicit --approve.

    NOTE: the Space reimplements this in JavaScript. The licence lists are
    shared via space/license_policy.json; these few rules are not, so keep
    them in step by hand (test_space_sync.py only covers the licence data).
    """
    blocking, needs_human = [], []

    if f["pickle_only"]:
        blocking.append("pickle-only weights: loading executes the file")
    if f["license_bucket"] == "non_commercial":
        blocking.append(f"licence {f['license']} forbids commercial use")
    if f["remote_code_external"]:
        repos = sorted({t.split("--")[0] for t in f["remote_code_external"]})
        blocking.append(
            f"executes code from another repo ({', '.join(repos)}); pinning "
            "this revision does not pin that code"
        )

    if f["license_bucket"] == "unclearable":
        needs_human.append(f"licence {f['license'] or 'not declared'} is undecidable")
    if f["license_bucket"] == "conditional":
        needs_human.append(f"licence {f['license']} carries obligations")
    if f["remote_code"] and not f["remote_code_external"]:
        needs_human.append("executes remote code on load")
    if f["gated"]:
        needs_human.append(f"gated ({f['gated']}): needs accepted terms and a token")

    verdict = "BLOCK" if blocking else ("REVIEW" if needs_human else "PASS")
    return verdict, blocking, needs_human


def mirror_patterns(findings, formats):
    """Exactly which files to pull, as an allowlist.

    Anything not matched is simply absent from the mirror -- including weight
    formats that did not exist when this was written.
    """
    allow = list(METADATA)
    for fmt in formats:
        allow += list(WEIGHTS[fmt])
    # A model that legitimately loads its own code needs that code mirrored
    # too; external-repo code is a BLOCK and never reaches here.
    if findings["remote_code"]:
        allow.append("*.py")
    return allow


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_bucket(s3, bucket, region):
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"  bucket {bucket} exists")
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "403"):
            raise

    kwargs = {"Bucket": bucket}
    if region != "us-east-1":  # us-east-1 rejects an explicit constraint
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
    s3.create_bucket(**kwargs)
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )
    # Versioning protects the audit trail, but non-current versions keep
    # billing and do not show up in `aws s3 ls`. At model sizes that adds up
    # fast, so expire them and clean up failed multipart uploads.
    s3.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "expire-noncurrent-versions",
                    "Status": "Enabled",
                    "Filter": {"Prefix": ""},
                    "NoncurrentVersionExpiration": {"NoncurrentDays": 7},
                    "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                }
            ]
        },
    )
    print(f"  created {bucket} (private, versioned, encrypted, lifecycle)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo_id")
    ap.add_argument("--revision", help="pin to this ref; default is current main")
    ap.add_argument("--bucket")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--create-bucket", action="store_true")
    ap.add_argument(
        "--approve",
        action="store_true",
        help="mirror despite REVIEW findings, recording that a human accepted them",
    )
    ap.add_argument(
        "--formats",
        default="safetensors",
        help="comma-separated weight formats to mirror: "
        + ",".join(WEIGHTS) + " (default: safetensors)",
    )
    ap.add_argument("--dry-run", action="store_true", help="audit only, touch nothing")
    args = ap.parse_args()

    print(f"\nauditing {args.repo_id}")
    try:
        info, findings = audit(args.repo_id, args.revision)
    except RepositoryNotFoundError:
        print(f"  NOT FOUND: {args.repo_id}")
        return 2
    except GatedRepoError:
        print("  GATED: accept the licence on the Hub and authenticate first")
        return 2

    verdict, blocking, needs_human = decide(findings)
    print(f"  revision  {findings['revision']}")
    print(f"  licence   {findings['license']} -> {findings['license_bucket']}")
    print(
        f"  weights   {len(findings['safetensors_files'])} safetensors, "
        f"{len(findings['pickle_files'])} pickle"
    )
    print(f"  verdict   {verdict}")
    for item in blocking:
        print(f"    BLOCK  {item}")
    for item in needs_human:
        print(f"    REVIEW {item}")

    if verdict == "BLOCK":
        print("\nrefusing to mirror. This is the gate doing its job.")
        return 1
    if verdict == "REVIEW" and not args.approve:
        print("\nneeds a human. Re-run with --approve to accept and record it.")
        return 1
    if args.dry_run:
        print("\ndry run: nothing downloaded or uploaded.")
        return 0
    if not args.bucket:
        print("\n--bucket is required to mirror.")
        return 2

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in WEIGHTS]
    if unknown:
        print("\nunknown format(s): " + ", ".join(unknown))
        return 2
    if "safetensors" in formats and not findings["safetensors_files"]:
        print("\nno safetensors in this repo; nothing safe to mirror.")
        return 1

    allow = mirror_patterns(findings, formats)
    print("\ndownloading revision " + findings["revision"][:12])
    print("  formats   " + ", ".join(formats))
    print("  allowlist " + ", ".join(allow))

    local = snapshot_download(
        args.repo_id, revision=findings["revision"], allow_patterns=allow
    )
    # Upload the files the allowlist selected -- NOT everything in the cache
    # directory. snapshot_download reuses a shared cache, so a full copy
    # pulled by some earlier run would otherwise end up in the mirror and the
    # policy would be silently wider than it reads.
    root = pathlib.Path(local)
    wanted = sorted(
        f.rfilename
        for f in info.siblings
        if any(fnmatch.fnmatch(f.rfilename, pat) for pat in allow)
    )
    missing = [name for name in wanted if not (root / name).is_file()]
    if missing:
        print("expected files absent after download: " + ", ".join(missing))
        return 1
    files = [root / name for name in wanted]

    s3 = boto3.client("s3", region_name=args.region)
    if args.create_bucket:
        ensure_bucket(s3, args.bucket, args.region)

    prefix = f"models/{args.repo_id}/{findings['revision']}"
    print(f"\nuploading to s3://{args.bucket}/{prefix}/")

    manifest_files, total = [], 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest, size = sha256(path), path.stat().st_size
        s3.upload_file(str(path), args.bucket, f"{prefix}/{rel}")
        manifest_files.append({"path": rel, "sha256": digest, "bytes": size})
        total += size
        print(f"  {rel}  ({size / 1e6:.1f} MB)")

    manifest = {
        "repo_id": args.repo_id,
        "formats": formats,
        "allow_patterns": allow,
        "revision": findings["revision"],
        "mirrored_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mirrored_by": boto3.client("sts").get_caller_identity()["Arn"],
        "verdict": verdict,
        "blocking": blocking,
        "accepted_by_human": needs_human if args.approve else [],
        "findings": findings,
        "pickle_files_left_behind": findings["pickle_files"],
        "files": manifest_files,
        "total_bytes": total,
    }
    s3.put_object(
        Bucket=args.bucket,
        Key=f"{prefix}/_manifest.json",
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
    )

    print(f"\nmirrored {len(files)} files, {total / 1e6:.1f} MB")
    print(f"manifest s3://{args.bucket}/{prefix}/_manifest.json")
    print(f"\nserve from: s3://{args.bucket}/{prefix}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
