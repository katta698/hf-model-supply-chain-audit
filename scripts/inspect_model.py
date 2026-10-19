"""Inspect a Hugging Face model repo without downloading the weights.

Answers the questions a security review would ask:
  - exactly which revision is this?
  - what license does it claim?
  - does it ship pickle-format weights (arbitrary code on load)?
  - does loading it require executing code fetched from the Hub?
"""

import json
import sys

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.errors import (
    GatedRepoError,
    HfHubHTTPError,
    RepositoryNotFoundError,
)

# Formats that unpickle on load -> arbitrary code execution.
PICKLE_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".ckpt")

api = HfApi()


def human(nbytes):
    if not nbytes:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unit == "GB":
            return f"{nbytes:.0f}{unit}" if unit == "B" else f"{nbytes:.1f}{unit}"
        nbytes /= 1024


def remote_code(repo_id, info):
    """Return the code targets that config.json's auto_map points at.

    This, not the presence of .py files, is what actually executes on load.
    Values look like "modeling_bert.BertModel" (code in this repo) or
    "other-org--other-repo--modeling_bert.BertModel" (a DIFFERENT repo).
    """
    if not any(f.rfilename == "config.json" for f in info.siblings):
        return []
    try:
        path = hf_hub_download(repo_id, "config.json", revision=info.sha)
        with open(path, encoding="utf-8") as fh:
            config = json.load(fh)
    except Exception:
        return []
    return sorted(set(config.get("auto_map", {}).values()))


def inspect(repo_id):
    print()
    print("=" * 70)
    print(repo_id)
    print("=" * 70)
    try:
        info = api.model_info(repo_id, files_metadata=True)
    except GatedRepoError:
        print("  GATED - access must be requested and accepted before download.")
        print("  Means: no CI job can pull this without a credentialed token.")
        return
    except RepositoryNotFoundError:
        print("  NOT FOUND (or private).")
        return
    except HfHubHTTPError as exc:
        print(f"  ERROR: {exc}")
        return

    license_ = (info.card_data or {}).get("license", "NOT DECLARED")
    print(f"  revision   : {info.sha}")
    print(f"  license    : {license_}")
    print(f"  downloads  : {info.downloads:,}/month")

    pickles, safetensors = [], []
    for f in info.siblings:
        name = f.rfilename
        if name.endswith(PICKLE_SUFFIXES):
            pickles.append((name, f.size))
        elif name.endswith(".safetensors"):
            safetensors.append((name, f.size))
    code = remote_code(repo_id, info)

    print()
    print("  weight files:")
    for name, size in safetensors:
        print(f"    [safe]   {name} ({human(size)})")
    for name, size in pickles:
        print(f"    [PICKLE] {name} ({human(size)})")
    if not safetensors and not pickles:
        print("    (none)")

    if code:
        print()
        print("  remote code (runs on load with trust_remote_code=True):")
        for target in code:
            print(f"    [CODE]   {target}")

    print()
    print("  findings:")
    if pickles and safetensors:
        print("    - ships BOTH formats; a default load may still pick the pickle")
    elif pickles:
        print("    - PICKLE ONLY: loading this executes whatever is in the file")
    elif safetensors:
        print("    - safetensors only: weights cannot carry code")
    if code:
        print("    - executes code fetched at load time; not reviewed by HF")
        if any("--" in target for target in code):
            print("      code lives in a SEPARATE repo; pinning this one is not enough")
    if license_ == "NOT DECLARED":
        print("    - NO LICENSE DECLARED: not commercially usable by default")


if __name__ == "__main__":
    repos = sys.argv[1:] or [
        "sentence-transformers/all-MiniLM-L6-v2",
        "jinaai/jina-embeddings-v2-base-en",
        "meta-llama/Llama-3.1-8B",
    ]
    for repo in repos:
        inspect(repo)
