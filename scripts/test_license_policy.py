"""Tests for the licence classifier. Run: python scripts/test_license_policy.py"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from license_policy import classify  # noqa: E402

CASES = [
    # (tag, expected bucket, why this case is here)
    ("apache-2.0", "permissive", "the common case"),
    ("MIT", "permissive", "tags are case-normalised"),
    ("cc-by-4.0", "permissive", "attribution only, commercially fine"),
    ("llama3.1", "conditional", "commercial use allowed, with obligations"),
    ("llama2", "conditional", "whole family matches by prefix"),
    ("gemma", "conditional", "acceptable-use policy attached"),
    ("openrail++", "conditional", "RAIL use restrictions"),
    ("cc-by-sa-4.0", "conditional", "share-alike reciprocity"),
    ("gpl-3.0", "conditional", "copyleft is an obligation, not a block"),
    ("cc-by-nc-4.0", "non_commercial", "cannot ship commercially"),
    (
        "cc-by-nc-sa-4.0",
        "non_commercial",
        "matches both NC and share-alike; stricter answer must win",
    ),
    ("other", "unclearable", "the tag decides nothing"),
    (None, "unclearable", "no tag at all"),
    ("", "unclearable", "empty tag"),
    (
        "some-vendor-license-2026",
        "unclearable",
        "unrecognised tag must NOT fail open to permissive",
    ),
]


def main():
    failures = []
    for tag, expected, why in CASES:
        actual = classify(tag)
        if actual != expected:
            failures.append(f"  classify({tag!r}) -> {actual!r}, expected {expected!r}  ({why})")

    if failures:
        print(f"FAILED {len(failures)}/{len(CASES)}")
        print("\n".join(failures))
        return 1
    print(f"ok - {len(CASES)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
