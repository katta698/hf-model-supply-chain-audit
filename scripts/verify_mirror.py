"""Fetch a mirrored model from S3, verify it, and prove it never touches the Hub.

This is the consuming half of the control. An inference container would do
exactly this at startup: pull from the bucket, check the bytes against the
manifest recorded at approval time, and load locally.

The checksum step is the point. Mirroring alone proves a model was approved
once; verifying on every pull proves the bytes have not changed since.

Usage:
    python scripts/verify_mirror.py --bucket my-mirror \
        --repo-id sentence-transformers/all-MiniLM-L6-v2
    python scripts/verify_mirror.py --bucket my-mirror --repo-id ... --tamper-test
"""

import argparse
import hashlib
import json
import os
import pathlib
import socket
import sys
import tempfile

import boto3


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def block_the_internet():
    """Make any direct outbound socket fail, so a silent Hub fetch cannot hide.

    A container would get this from its subnet having no route out. Here we
    enforce it in-process, which is enough to prove the code path never needs
    the network -- S3 access goes through boto3 before this is installed.
    """
    def refuse(*_args, **_kwargs):
        raise OSError("outbound network disabled: this step must not reach the Hub")

    socket.socket = refuse
    socket.create_connection = refuse


def latest_revision(s3, bucket, repo_id):
    """Newest mirrored revision for a repo, by manifest timestamp."""
    prefix = f"models/{repo_id}/"
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix, Delimiter="/"
    )
    revisions = [
        cp["Prefix"].rstrip("/").rsplit("/", 1)[-1]
        for page in pages
        for cp in page.get("CommonPrefixes", [])
    ]
    if not revisions:
        raise SystemExit(f"no mirrored revisions under s3://{bucket}/{prefix}")
    if len(revisions) > 1:
        print(f"  {len(revisions)} revisions mirrored; using the newest manifest")
    newest, newest_at = None, ""
    for rev in revisions:
        body = s3.get_object(Bucket=bucket, Key=f"{prefix}{rev}/_manifest.json")["Body"]
        at = json.loads(body.read())["mirrored_at"]
        if at > newest_at:
            newest, newest_at = rev, at
    return newest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--revision", help="default: newest mirrored revision")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument(
        "--tamper-test",
        action="store_true",
        help="corrupt one byte after download to show verification catching it",
    )
    args = ap.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    revision = args.revision or latest_revision(s3, args.bucket, args.repo_id)
    prefix = f"models/{args.repo_id}/{revision}"

    print(f"\nsource    s3://{args.bucket}/{prefix}/")
    manifest = json.loads(
        s3.get_object(Bucket=args.bucket, Key=f"{prefix}/_manifest.json")["Body"].read()
    )
    print(f"revision  {manifest['revision']}")
    print(f"approved  {manifest['mirrored_at']}  verdict {manifest['verdict']}")
    print(f"by        {manifest['mirrored_by']}")
    if manifest.get("pickle_files_left_behind"):
        left = manifest["pickle_files_left_behind"]
        print(f"excluded  {len(left)} pickle file(s) never entered the mirror")

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        total = 0
        print(f"\ndownloading {len(manifest['files'])} files")
        for entry in manifest["files"]:
            dest = root / entry["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(args.bucket, f"{prefix}/{entry['path']}", str(dest))
            total += entry["bytes"]

        if args.tamper_test:
            victim = root / manifest["files"][-1]["path"]
            data = bytearray(victim.read_bytes())
            data[0] ^= 0xFF
            victim.write_bytes(data)
            print(f"  TAMPER TEST: flipped one byte in {victim.name}")

        # From here on, nothing may reach the network.
        block_the_internet()

        print("\nverifying checksums (outbound network now disabled)")
        bad = []
        for entry in manifest["files"]:
            actual = sha256(root / entry["path"])
            if actual != entry["sha256"]:
                bad.append(entry["path"])
                print(f"  MISMATCH {entry['path']}")
                print(f"    expected {entry['sha256']}")
                print(f"    actual   {actual}")

        if bad:
            print(f"\nFAILED: {len(bad)} file(s) do not match the approved manifest.")
            print("A container would refuse to start here.")
            return 1

        print(f"  all {len(manifest['files'])} files match ({total / 1e6:.1f} MB)")

        # Offline sanity check: safetensors carries a JSON header, so the file
        # can be shown to be a real model artifact without loading torch.
        weights = next(
            (f["path"] for f in manifest["files"] if f["path"].endswith(".safetensors")),
            None,
        )
        if weights:
            with open(root / weights, "rb") as fh:
                header_len = int.from_bytes(fh.read(8), "little")
                header = json.loads(fh.read(header_len))
            tensors = {k: v for k, v in header.items() if k != "__metadata__"}
            print(f"\n{weights}: {len(tensors)} tensors, no code, parsed offline")
            for name in list(tensors)[:3]:
                t = tensors[name]
                print(f"  {name}  {t['dtype']}  {t['shape']}")

        os.environ["HF_HUB_OFFLINE"] = "1"
        print("\nVERIFIED. To load, with no Hub access required:")
        print(f'  AutoModel.from_pretrained("{root}")')

    print("\nThe Hub was never contacted. Everything came from S3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
