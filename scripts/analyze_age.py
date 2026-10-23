"""Test whether repo age, not popularity, explains pickle-only risk.

The 600-model audit found pickle-only weights are *more* common in the top 100
(17.0%) than in ranks 101-600 (13.0%) -- the opposite of the obvious guess.

Hypothesis: safetensors landed in late 2022 and became the default during 2023.
The most-downloaded list is full of pre-safetensors classics (BERT, CLIP,
wav2vec2), so the apparent "popularity" effect may just be age.

The decisive test is not "are old models worse" -- that is expected and tells us
little. It is whether the rank effect *survives* controlling for age. If within
a single year cohort the top 100 and the tail look the same, age explains it.

Usage:
    python scripts/analyze_age.py [data/top_models.jsonl]
"""

import json
import pathlib
import sys


def pickle_only(record):
    return bool(record["pickle_files"]) and not record["safetensors_files"]


def year_of(record):
    created = record.get("created_at")
    return int(created[:4]) if created else None


def pct(rows, predicate):
    if not rows:
        return None
    return sum(1 for r in rows if predicate(r)) / len(rows) * 100


def bar(value, width=28):
    return "#" * round(value / 100 * width)


def main():
    path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "data/top_models.jsonl")
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    ok = [r for r in rows if r["status"] == "ok" and r.get("created_at")]
    missing = len(rows) - len(ok)

    print(f"{len(ok)} models with creation dates" + (f" ({missing} without)" if missing else ""))

    # 1. Does pickle-only risk track creation year?
    print()
    print("pickle-only weights, by the year the repo was created")
    print("  safetensors shipped late 2022 and became the default during 2023")
    print()
    years = sorted({year_of(r) for r in ok})
    for year in years:
        cohort = [r for r in ok if year_of(r) == year]
        value = pct(cohort, pickle_only)
        print(f"    {year}  n={len(cohort):>3}  {value:>5.1f}%  {bar(value)}")

    # 2. Are the most-downloaded models actually older?
    print()
    print("repo age by download rank")
    top = [r for r in ok if r["rank"] <= 100]
    tail = [r for r in ok if r["rank"] > 100]
    for label, group in (("top 100", top), ("rank 101-600", tail)):
        dates = sorted(r["created_at"][:7] for r in group)
        median = dates[len(dates) // 2]
        pre2023 = sum(1 for r in group if year_of(r) < 2023) / len(group) * 100
        print(
            f"    {label:<14} median created {median}"
            f"   created before 2023: {pre2023:>4.1f}%"
        )

    # 3. The decisive test: does the rank effect survive controlling for age?
    print()
    print("pickle-only, holding creation year fixed")
    print("  if the rank gap disappears within a cohort, age explains it")
    print()
    print(f"    {'year':<6}{'top 100':>18}{'rank 101-600':>18}")
    for year in years:
        cohort_top = [r for r in ok if year_of(r) == year and r["rank"] <= 100]
        cohort_tail = [r for r in ok if year_of(r) == year and r["rank"] > 100]
        if len(cohort_top) < 5 or len(cohort_tail) < 5:
            continue  # too few to compare honestly
        a, b = pct(cohort_top, pickle_only), pct(cohort_tail, pickle_only)
        print(
            f"    {year:<6}{a:>12.1f}% (n={len(cohort_top):>3})"
            f"{b:>12.1f}% (n={len(cohort_tail):>3})"
        )

    # 4. Same question for remote code, where the tail genuinely was worse.
    print()
    print("remote code on load, by creation year")
    print()
    for year in years:
        cohort = [r for r in ok if year_of(r) == year]
        value = pct(cohort, lambda r: bool(r["remote_code"]))
        print(f"    {year}  n={len(cohort):>3}  {value:>5.1f}%  {bar(value)}")

    # 5. Same controlled test for remote code, where the tail looked worse.
    print()
    print("remote code, holding creation year fixed")
    print()
    print(f"    {'year':<6}{'top 100':>18}{'rank 101-600':>18}")
    has_code = lambda r: bool(r["remote_code"])  # noqa: E731
    for year in years:
        cohort_top = [r for r in ok if year_of(r) == year and r["rank"] <= 100]
        cohort_tail = [r for r in ok if year_of(r) == year and r["rank"] > 100]
        if len(cohort_top) < 5 or len(cohort_tail) < 5:
            continue
        a, b = pct(cohort_top, has_code), pct(cohort_tail, has_code)
        print(
            f"    {year:<6}{a:>12.1f}% (n={len(cohort_top):>3})"
            f"{b:>12.1f}% (n={len(cohort_tail):>3})"
        )


if __name__ == "__main__":
    main()
