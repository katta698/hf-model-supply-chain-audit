"""Audit the most-downloaded models on the Hub for supply-chain risk.

Produces one JSON record per model plus a summary, so the claim
"N% of the top models still ship pickle weights" has evidence behind it.

Usage:
    python scripts/scan_top_models.py --limit 100 --out data/top_models.jsonl
"""

import argparse
import json
import pathlib
import sys

from huggingface_hub import HfApi
from huggingface_hub.errors import HfHubHTTPError

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from inspect_model import PICKLE_SUFFIXES, remote_code  # noqa: E402

api = HfApi()

# Licenses a commercial review would normally wave through without escalation.
PERMISSIVE = {
    "apache-2.0",
    "mit",
    "bsd",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc0-1.0",
    "unlicense",
    "isc",
}


def audit(summary):
    """Audit one model. `summary` is a ModelInfo from list_models()."""
    repo_id = summary.id
    record = {
        "repo_id": repo_id,
        "downloads": summary.downloads or 0,
        "status": "ok",
    }
    try:
        info = api.model_info(repo_id, files_metadata=True)
    except HfHubHTTPError as exc:
        record["status"] = f"error:{getattr(exc.response, 'status_code', None)}"
        return record

    pickles, safetensors = [], []
    for f in info.siblings:
        if f.rfilename.endswith(PICKLE_SUFFIXES):
            pickles.append(f.rfilename)
        elif f.rfilename.endswith(".safetensors"):
            safetensors.append(f.rfilename)

    code = remote_code(repo_id, info)
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
            "license_permissive": license_ in PERMISSIVE,
            "license_declared": license_ is not None,
        }
    )
    return record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--out", default="data/top_models.jsonl")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    # huggingface_hub 2.x dropped `direction`; sort= is already descending.
    models = list(api.list_models(sort="downloads", limit=args.limit))
    print(f"auditing {len(models)} models")

    records = []
    with out.open("w", encoding="utf-8") as fh:
        for i, summary in enumerate(models, 1):
            record = audit(summary)
            records.append(record)
            fh.write(json.dumps(record) + "\n")
            flags = []
            if record.get("pickle_files"):
                flags.append("pickle")
            if record.get("remote_code_external"):
                flags.append("external-code")
            elif record.get("remote_code"):
                flags.append("remote-code")
            if record["status"] != "ok":
                flags.append(record["status"])
            print(f"  {i:>3}. {record['repo_id'][:52]:<52} {' '.join(flags)}")

    report(records, out)


def report(records, out):
    ok = [r for r in records if r["status"] == "ok"]
    n = len(ok)
    if not n:
        print("no models audited successfully")
        return

    def pct(subset):
        return f"{len(subset):>3} / {n}  ({len(subset) / n * 100:.0f}%)"

    pickle = [r for r in ok if r["pickle_files"]]
    pickle_only = [r for r in ok if r["pickle_files"] and not r["safetensors_files"]]
    code = [r for r in ok if r["remote_code"]]
    external = [r for r in ok if r["remote_code_external"]]
    undeclared = [r for r in ok if not r["license_declared"]]
    non_permissive = [
        r for r in ok if r["license_declared"] and not r["license_permissive"]
    ]
    gated = [r for r in ok if r["gated"]]

    print()
    print("=" * 62)
    print(f"SUMMARY  ({n} audited of {len(records)} listed)")
    print("=" * 62)
    print(f"  ship any pickle weights       {pct(pickle)}")
    print(f"  pickle with no safetensors    {pct(pickle_only)}")
    print(f"  execute remote code on load   {pct(code)}")
    print(f"    code from a DIFFERENT repo  {pct(external)}")
    print(f"  gated (token + accepted EULA) {pct(gated)}")
    print(f"  no license declared           {pct(undeclared)}")
    print(f"  licence not on permissive list{pct(non_permissive)}")
    print()
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
