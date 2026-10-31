"""Build the Lambda layer for CPU inference, reproducibly.

The layer is ~123 MB of third-party wheels. Those are a build artifact, not
source, so they are gitignored and rebuilt from pinned versions here.

Two things make this awkward enough to need a script rather than a one-liner:

  * The wheels must be Linux x86_64 for the Lambda runtime, and this is built
    from Windows -- so pip needs explicit --platform rather than resolving
    for the host.
  * The packages do not agree on a platform tag. onnxruntime publishes
    manylinux_2_28; tokenizers publishes manylinux_2_17. Passing one tag
    fails on whichever package disagrees, so all are passed and pip picks.

It also strips what pip drags in and Lambda must not have: tokenizers depends
on huggingface_hub, which brings an HTTP client and a Hub client. Shipping
those into a subnet that is deliberately cut off from the Hub would be
careless at best -- the whole point is that this runtime cannot reach it.

Usage:
    python scripts/build_lambda_layer.py
"""

import pathlib
import shutil
import subprocess
import sys

# Pinned. An unpinned layer means the bytes serving inference change without
# anything in the repo changing -- the same failure the mirror exists to stop.
PACKAGES = [
    "onnxruntime==1.31.1",
    "numpy==2.4.6",
    "tokenizers==0.23.3",
]

PLATFORMS = [
    "manylinux_2_28_x86_64",  # onnxruntime
    "manylinux_2_17_x86_64",  # tokenizers, numpy
    "manylinux2014_x86_64",
]
PYTHON_VERSION = "3.13"

# Pulled in transitively, unnecessary at runtime, and in the case of the HTTP
# and Hub clients, actively unwanted in an air-gapped subnet.
STRIP = [
    "huggingface_hub", "hf_xet", "requests", "urllib3", "certifi",
    "charset_normalizer", "idna", "filelock", "fsspec", "tqdm", "packaging",
    "anyio", "click", "colorama", "h11", "httpcore2", "httpx2", "truststore",
    "_yaml", "yaml", "bin",
]

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = ROOT / "terraform" / "lambda-serve" / "layer" / "python"


def main():
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir(parents=True)

    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--only-binary=:all:"]
    for platform in PLATFORMS:
        cmd += ["--platform", platform]
    cmd += ["--python-version", PYTHON_VERSION, "--target", str(TARGET), *PACKAGES]

    print("installing " + ", ".join(PACKAGES))
    subprocess.run(cmd, check=True)

    removed = []
    for name in STRIP:
        path = TARGET / name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(name)
    for pattern in ("**/__pycache__", "**/*.dist-info", "**/tests"):
        for path in TARGET.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    if removed:
        print("stripped: " + ", ".join(sorted(removed)))

    total = sum(f.stat().st_size for f in TARGET.rglob("*") if f.is_file())
    print(f"\nlayer: {total / 1e6:.0f} MB unzipped")
    print(f"       {sorted(p.name for p in TARGET.iterdir() if p.is_dir())}")
    if total > 250e6:
        print("WARNING: over Lambda's 250 MB unzipped limit")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
