"""Audit the most-downloaded models on the Hub for supply-chain risk.

Produces one JSON record per model plus a summary, so the claim
"N% of the top models still ship pickle weights" has evidence behind it.

Results are also broken down by rank band, which is the only way to test
whether the long tail of the Hub is worse than its most-scrutinised models.

Usage:
    python scripts/scan_top_models.py --limit 600 --out data/top_models.jsonl

Re-running with the same --out resumes: already-audited repos are skipped, so
a rate-limit interruption costs only the remaining models.
"""

import argparse
import json
import pathlib
import sys
import time

from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from inspect_model import PICKLE_SUFFIXES, remote_code  # noqa: E402

from license_policy import BUCKETS, classify  # noqa: E402

api = HfApi()

RETRY_DELAYS = (2, 4, 8, 16, 32)
BAND_SIZE = 100


def retryable(exc):
    """True for throttling and server errors, which are worth waiting out."""
    status = getattr(exc.response, "status_code", None)
    return status == 429 or (status or 0) >= 500


def with_retry(fn, *args, **kwargs):
    """Call fn, backing off on throttling. Raises if every attempt fails."""
    for delay in RETRY_DELAYS:
        try:
            return fn(*args, **kwargs)
        except HfHubHTTPError as exc:
            if not retryable(exc):
                raise
            print(f"       throttled, waiting {delay}s")
            time.sleep(delay)
    return fn(*args, **kwargs)


def audit(summary, rank):
    """Audit one model. `summary` is a ModelInfo from list_models()."""
    repo_id = summary.id
    record = {
        "rank": rank,
        "repo_id": repo_id,
        "downloads": summary.downloads or 0,
        "status": "ok",
    }
    try:
        info = with_retry(api.model_info, repo_id, files_metadata=True)
        code = with_retry(remote_code, repo_id, info)
    except HfHubHTTPError as exc:
        record["status"] = f"error:{getattr(exc.response, 'status_code', None)}"
        return record

    pickles, safetensors = [], []
    for f in info.siblings:
        if f.rfilename.endswith(PICKLE_SUFFIXES):
            pickles.append(f.rfilename)
        elif f.rfilename.endswith(".safetensors"):
            safetensors.append(f.rfilename)

    license_ = (info.card_data or {}).get("license") or None

    record.update(
        {
            "revision": info.sha,
            # False | "auto" | "manual". Metadata stays readable when gated;
            # only file downloads require an accepted licence + token.
            "gated": info.gated or False,
            "license": license_,
            "pipeline_tag": info.pipeline_tag,
            "pickle_files": pickles,
            "safetensors_files": safetensors,
            "remote_code": code,
            # Code in another repo: pinning this revision does not pin that code.
            "remote_code_external": [t for t in code if "--" in t],
            "license_bucket": classify(license_),
            "license_declared": license_ is not None,
        }
    )
    return record


def load_existing(out):
    """Return {repo_id: record} from a previous run, for resume."""
    if not out.exists():
        return {}
    done = {}
    with out.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            # Only completed audits count; errored rows get retried.
            if record.get("status") == "ok":
                done[record["repo_id"]] = record
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="data/top_models.jsonl")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # huggingface_hub 2.x dropped `direction`; sort= is already descending.
    models = list(api.list_models(sort="downloads", limit=args.limit))
    done = load_existing(out)
    if done:
        print(f"resuming: {len(done)} already audited")
    print(f"listing {len(models)} models")

    records = []
    for rank, summary in enumerate(models, 1):
        cached = done.get(summary.id)
        if cached:
            # Backfill rank for rows written before ranks were recorded.
            cached["rank"] = rank
            records.append(cached)
            continue
        record = audit(summary, rank)
        records.append(record)
        flags = []
        if record.get("pickle_files"):
            flags.append("pickle" if record["safetensors_files"] else "PICKLE-ONLY")
        if record.get("remote_code_external"):
            flags.append("external-code")
        elif record.get("remote_code"):
            flags.append("remote-code")
        if record["status"] != "ok":
            flags.append(record["status"])
        print(f"  {rank:>4}. {record['repo_id'][:52]:<52} {' '.join(flags)}")

    # Rewrite in rank order so the file is stable regardless of resume history.
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")

    report(records, out)


def stats(rows):
    """The audit findings for a set of rows, as fractions of the set."""
    n = len(rows)
    if not n:
        return None
    return {
        "n": n,
        "pickle": sum(1 for r in rows if r["pickle_files"]),
        "pickle_only": sum(
            1 for r in rows if r["pickle_files"] and not r["safetensors_files"]
        ),
        "code": sum(1 for r in rows if r["remote_code"]),
        "external": sum(1 for r in rows if r["remote_code_external"]),
        "gated": sum(1 for r in rows if r["gated"]),
        "undeclared": sum(1 for r in rows if not r["license_declared"]),
        **{
            bucket: sum(1 for r in rows if r["license_bucket"] == bucket)
            for bucket in BUCKETS
        },
    }


def report(records, out):
    ok = [r for r in records if r["status"] == "ok"]
    failed = [r for r in records if r["status"] != "ok"]
    overall = stats(ok)
    if not overall:
        print("no models audited successfully")
        return

    n = overall["n"]

    def pct(key):
        count = overall[key]
        return f"{count:>4} / {n}  ({count / n * 100:.0f}%)"

    print()
    print("=" * 64)
    print(f"SUMMARY  ({n} audited, {len(failed)} failed, of {len(records)} listed)")
    print("=" * 64)
    print(f"  ship any pickle weights       {pct('pickle')}")
    print(f"  pickle with no safetensors    {pct('pickle_only')}")
    print(f"  execute remote code on load   {pct('code')}")
    print(f"    code from a DIFFERENT repo  {pct('external')}")
    print(f"  gated (token + accepted EULA) {pct('gated')}")
    print()
    print("  licence, by what a review would decide:")
    print(f"    permissive      ship it    {pct('permissive')}")
    print(f"    conditional     obligations{pct('conditional')}")
    print(f"    non-commercial  blocked    {pct('non_commercial')}")
    print(f"    unclearable     read it    {pct('unclearable')}")
    print(f"      of which, no tag at all  {pct('undeclared')}")

    # The long-tail test: does risk rise as popularity falls?
    bands = []
    for start in range(1, max(r["rank"] for r in ok) + 1, BAND_SIZE):
        rows = [r for r in ok if start <= r["rank"] < start + BAND_SIZE]
        band = stats(rows)
        if band:
            bands.append((f"{start}-{start + BAND_SIZE - 1}", band))

    if len(bands) > 1:
        print()
        print("  by download rank (is the long tail worse?)")
        print("    rank        n   pickle-only   remote-code   unclearable")
        for label, band in bands:
            m = band["n"]
            print(
                f"    {label:<10} {m:>3}"
                f"   {band['pickle_only'] / m * 100:>9.0f}%"
                f"   {band['code'] / m * 100:>9.0f}%"
                f"   {band['unclearable'] / m * 100:>9.0f}%"
            )

    print()
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
