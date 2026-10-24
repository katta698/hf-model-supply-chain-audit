"""Emit the markdown tables used in the README and dataset card.

Hand-copied numbers go stale. The first 600-model scan and a re-scan three days
later disagreed on every headline count, because the Hub moved underneath them
-- and a card whose numbers do not match its own data file is exactly the
failure this project is about. So the tables are generated from the data.

Usage:
    python scripts/card_stats.py [data/top_models.jsonl]
"""

import json
import pathlib
import sys

PICKLE_ONLY = lambda r: bool(r["pickle_files"]) and not r["safetensors_files"]  # noqa: E731
REMOTE_CODE = lambda r: bool(r["remote_code"])  # noqa: E731
EXTERNAL = lambda r: bool(r["remote_code_external"])  # noqa: E731
UNCLEARABLE = lambda r: r["license_bucket"] == "unclearable"  # noqa: E731
NO_TAG = lambda r: not r["license_declared"]  # noqa: E731
GATED = lambda r: bool(r["gated"])  # noqa: E731


def year(record):
    return int(record["created_at"][:4]) if record.get("created_at") else None


def share(rows, predicate):
    return sum(1 for r in rows if predicate(r)) / len(rows) * 100


def count(rows, predicate):
    return sum(1 for r in rows if predicate(r))


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data/top_models.jsonl")
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(ok)
    top = [r for r in ok if r["rank"] <= 100]
    tail = [r for r in ok if r["rank"] > 100]

    def row(label, predicate, bold=False):
        k = count(ok, predicate)
        mark = "**" if bold else ""
        return f"| {mark}{label}{mark} | {mark}{k} / {n} ({k / n * 100:.0f}%){mark} |"

    print("## Findings\n")
    print("| Property | Count |")
    print("|---|---|")
    print(row("Ship at least one pickle-format weight file", lambda r: r["pickle_files"]))
    print(row("Ship pickle with no safetensors alternative", PICKLE_ONLY, bold=True))
    print(row("Execute remote code on load (`auto_map`)", REMOTE_CODE))
    print(row("— where that code lives in a *different* repo", EXTERNAL))
    print(row("Gated (requires token + accepted terms)", GATED))

    print("\n### Licence buckets\n")
    print("| Bucket | Count |")
    print("|---|---|")
    for bucket in ("permissive", "conditional", "non_commercial", "unclearable"):
        k = count(ok, lambda r, b=bucket: r["license_bucket"] == b)
        print(f"| `{bucket}` | {k} / {n} ({k / n * 100:.0f}%) |")
    print(f"\nOf the unclearable group, {count(ok, NO_TAG)} declare no licence at all.")

    print("\n### Top 100 vs the tail\n")
    print("| | top 100 | rank 101–600 | ratio |")
    print("|---|---|---|---|")
    for label, predicate in (
        ("pickle-only", PICKLE_ONLY),
        ("remote code on load", REMOTE_CODE),
        ("licence unclearable", UNCLEARABLE),
        ("no licence tag", NO_TAG),
    ):
        a, b = share(top, predicate), share(tail, predicate)
        print(f"| {label} | {a:.1f}% | {b:.1f}% | {b / a:.1f}× |")

    print("\n### By creation year\n")
    print("| Repo created | n | pickle-only | remote code |")
    print("|---|---|---|---|")
    for y in sorted({year(r) for r in ok if year(r)}):
        cohort = [r for r in ok if year(r) == y]
        print(
            f"| {y} | {len(cohort)} | {share(cohort, PICKLE_ONLY):.1f}% "
            f"| {share(cohort, REMOTE_CODE):.1f}% |"
        )

    print("\n### Remote code, holding creation year fixed\n")
    for y in sorted({year(r) for r in ok if year(r)}):
        ct = [r for r in top if year(r) == y]
        cl = [r for r in tail if year(r) == y]
        if len(ct) < 5 or len(cl) < 5:
            continue
        print(
            f"  {y}: top 100 {share(ct, REMOTE_CODE):.1f}% (n={len(ct)}), "
            f"tail {share(cl, REMOTE_CODE):.1f}% (n={len(cl)})"
        )

    pre = lambda g: share(g, lambda r: year(r) and year(r) < 2023)  # noqa: E731
    print(
        f"\n  pre-2023 share: top 100 {pre(top):.0f}%, tail {pre(tail):.0f}%"
        f"\n  external-repo code: {count(ok, EXTERNAL)} models"
    )


if __name__ == "__main__":
    main()
