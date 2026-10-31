"""Serve embeddings from the mirrored model, inside a subnet with no egress.

This is the half P1 did not cover. P1 proved an approved model could be got
into the boundary safely. This proves it can actually do useful work there --
that "sovereign inference" is a deployment, not a slide.

On cold start it pulls the approved revision from S3, verifies every byte
against the manifest recorded at approval time, and loads it. On each request
it returns embeddings, tagged with the model revision that produced them, so
any stored vector can be traced back to an audited artifact.

No weights are fetched at runtime from anywhere but the mirror bucket, and the
subnet has no route to the internet, so it could not reach the Hub if it tried.
"""

import hashlib
import json
import os
import pathlib
import time

import boto3
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

BUCKET = os.environ["MIRROR_BUCKET"]
REPO = os.environ["MODEL_REPO"]
WEIGHTS = os.environ.get("MODEL_FILE", "onnx/model_quint8_avx2.onnx")
LOCAL = pathlib.Path("/tmp/model")

s3 = boto3.client("s3")

# Populated on cold start, reused across warm invocations.
STATE = {}


def newest_revision():
    prefix = f"models/{REPO}/"
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=BUCKET, Prefix=prefix, Delimiter="/"
    )
    revisions = [
        cp["Prefix"].rstrip("/").rsplit("/", 1)[-1]
        for page in pages
        for cp in page.get("CommonPrefixes", [])
    ]
    if not revisions:
        raise RuntimeError(f"nothing mirrored under s3://{BUCKET}/{prefix}")
    return sorted(revisions)[-1]


def fetch_and_verify(revision):
    """Download the approved revision and check it against its manifest.

    Verification is not ceremony. The manifest is what was audited; the bytes
    in the bucket are what will run. Checking them on every cold start is the
    only thing that connects the two.
    """
    prefix = f"models/{REPO}/{revision}"
    manifest = json.loads(
        s3.get_object(Bucket=BUCKET, Key=f"{prefix}/_manifest.json")["Body"].read()
    )

    needed = {WEIGHTS, "tokenizer.json"}
    checked = 0
    for entry in manifest["files"]:
        if entry["path"] not in needed:
            continue
        dest = LOCAL / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(BUCKET, f"{prefix}/{entry['path']}", str(dest))

        digest = hashlib.sha256()
        with open(dest, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise RuntimeError(
                f"{entry['path']} does not match the approved manifest; refusing to serve"
            )
        checked += 1

    if checked != len(needed):
        raise RuntimeError(
            f"manifest is missing required files: wanted {sorted(needed)}"
        )
    return manifest


def load():
    """Cold-start work: fetch, verify, build the session."""
    started = time.monotonic()
    revision = newest_revision()
    manifest = fetch_and_verify(revision)

    session = ort.InferenceSession(
        str(LOCAL / WEIGHTS),
        providers=["CPUExecutionProvider"],
        sess_options=_single_threaded(),
    )
    tokenizer = Tokenizer.from_file(str(LOCAL / "tokenizer.json"))
    # This model ships tokenizer.json with padding fixed at 128 tokens. Left
    # alone, a 16-token sentence costs the same compute as a 128-token one --
    # 8x of nothing. Pad to the longest item in the batch instead.
    tokenizer.no_padding()
    tokenizer.enable_truncation(max_length=256)
    tokenizer.enable_padding()

    STATE.update(
        revision=revision,
        approved_at=manifest["mirrored_at"],
        verdict=manifest["verdict"],
        session=session,
        tokenizer=tokenizer,
        inputs={i.name for i in session.get_inputs()},
        cold_start_s=round(time.monotonic() - started, 2),
    )


def _single_threaded():
    # Lambda gives fractional vCPU below 1769 MB; letting ORT spawn a thread
    # pool it cannot schedule makes latency worse, not better.
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    return opts


def embed(texts):
    tokenizer, session = STATE["tokenizer"], STATE["session"]
    encoded = tokenizer.encode_batch(texts)

    ids = np.array([e.ids for e in encoded], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
    feed = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in STATE["inputs"]:
        feed["token_type_ids"] = np.zeros_like(ids)

    STATE["last_shape"] = [int(ids.shape[0]), int(ids.shape[1])]
    STATE["last_real_tokens"] = int(mask.sum())
    hidden = session.run(None, feed)[0]

    # Mean pooling over real tokens only, then L2 normalise -- what
    # sentence-transformers does for this model.
    expanded = mask[..., None].astype(np.float32)
    pooled = (hidden * expanded).sum(axis=1) / np.clip(expanded.sum(axis=1), 1e-9, None)
    return pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9, None)


def lambda_handler(event, context):
    cold = not STATE
    if cold:
        load()

    texts = event.get("texts") or ["hello from a subnet with no route to the internet"]
    started = time.monotonic()
    vectors = embed(texts)
    inference_ms = round((time.monotonic() - started) * 1000, 1)

    # Cosine similarity between every pair. A quantised model that loaded
    # but produces garbage still returns plausible-looking floats; ordering
    # related pairs above unrelated ones is what actually proves it works.
    sims = None
    if 1 < len(texts) <= 8:
        sims = [
            [i, j, round(float(np.dot(vectors[i], vectors[j])), 3)]
            for i in range(len(texts))
            for j in range(i + 1, len(texts))
        ]

    return {
        "similarities": sims,
        "model": {
            "repo": REPO,
            "revision": STATE["revision"],
            "file": WEIGHTS,
            "approved_at": STATE["approved_at"],
            "verdict_at_approval": STATE["verdict"],
        },
        "count": len(texts),
        "padded_seq_len": STATE["last_shape"][1],
        "real_tokens_total": STATE["last_real_tokens"],
        "dimensions": int(vectors.shape[1]),
        "cold_start": cold,
        "cold_start_s": STATE["cold_start_s"] if cold else None,
        "inference_ms": inference_ms,
        "first_vector_head": [round(float(v), 4) for v in vectors[0][:8]],
    }
