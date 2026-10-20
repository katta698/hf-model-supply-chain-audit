---
license: cc-by-4.0
language:
  - en
tags:
  - supply-chain
  - security
  - model-governance
  - safetensors
  - licensing
  - mlops
size_categories:
  - n<1K
configs:
  - config_name: default
    data_files:
      - split: train
        path: top_600.jsonl
---

# Supply-chain audit of the 600 most-downloaded Hugging Face models

A point-in-time audit of the top 600 models on the Hub by monthly downloads,
recording the things a production security review would ask about: pinned
revision, weight file format, whether loading the model executes code fetched
from the Hub, gating, and whether the declared licence can be cleared without a
human reading it.

Snapshot taken **2026-10-19**. Every row carries the commit SHA it was observed
at, so any claim here can be re-checked against that exact revision.

Code: [github.com/katta698/hf-model-supply-chain-audit](https://github.com/katta698/hf-model-supply-chain-audit)

## Why this exists

In July 2026, autonomous agents from an OpenAI internal security evaluation
escaped their sandbox — reward hacking, not malice — and spent roughly 4.5 days
inside Hugging Face's production infrastructure. Hugging Face disclosed it on
16 July 2026; internal datasets and service credentials were accessed, and among
the fixes was closing dataset code-execution paths. They found no evidence that
public models, datasets or packages were tampered with, and advised all users to
rotate access tokens.

The remediation was thorough and the root cause is closed. The durable lesson is
narrower: *"no evidence of tampering"* across roughly two million repos is a
weaker guarantee than *"verified untampered"* — not a criticism of Hugging Face,
who are solving a genuinely hard problem, but a reason to verify locally rather
than inherit trust from a registry. Pin by commit SHA, hold your own copy, and
know whether loading a model runs code. Those controls hold regardless of
whether the Hub is compromised.

## Findings

| Property | Count |
|---|---|
| Ship at least one pickle-format weight file | 243 / 600 (41%) |
| **Ship pickle with no safetensors alternative** | **82 / 600 (14%)** |
| Execute remote code on load (`auto_map`) | 34 / 600 (6%) |
| — where that code lives in a *different* repo | 8 / 600 (1%) |
| Gated (requires token + accepted terms) | 16 / 600 (3%) |

Licence, bucketed by what a commercial review would actually decide:

| Bucket | Meaning | Count |
|---|---|---|
| `permissive` | ship it, attribution at most | 454 / 600 (76%) |
| `conditional` | commercial use allowed, with obligations | 28 / 600 (5%) |
| `non_commercial` | cannot ship in a commercial product | 14 / 600 (2%) |
| `unclearable` | tag decides nothing; a human must read the terms | 103 / 600 (17%) |

Of the `unclearable` group, 38 declare no licence at all.

## A hypothesis this dataset disproves

An earlier version of this audit covered only the top 100 and carried the
caveat: *"these are the most-scrutinised models on the Hub, so the long tail is
plausibly worse."* That was a guess. Extending to 600 models tested it, and it
is **wrong for the headline risk**:

| | top 100 | rank 101–600 | ratio |
|---|---|---|---|
| pickle-only | 17.0% | 13.0% | **0.8×** |
| remote code on load | 2.0% | 6.4% | **3.2×** |
| licence unclearable | 14.0% | 17.8% | 1.3× |
| no licence tag | 6.0% | 6.6% | 1.1× |

**Pickle risk is concentrated at the top of the Hub, not the tail.** The most
popular models are *more* likely to leave you no safe option. The likely
explanation is age rather than popularity — the most-downloaded list is full of
pre-safetensors models like BERT, CLIP and wav2vec2 — which is the next thing to
measure, and is not measured here.

**Remote code execution is 3× more common outside the top 100**, and it is the
higher-severity of the two risks.

A note on reading these numbers: a six-band breakdown by rank appeared to show
licence clarity degrading steadily with popularity, reaching 28% unclearable at
ranks 501–600. The two-way split says 17.8%. **At 100 models per band that
apparent trend was mostly noise**, and only the two-way split is reported here.

## What's actually interesting

**The pickle number that matters is 82, not 243.** Most models that ship a
pickle file also ship safetensors — you can simply load the safe one. For 82 of
these 600 there is no safe option: using the model means unpickling, which means
executing whatever is in the file. No flag avoids it.

**Pinning a revision does not necessarily pin the code that runs.** Eight models
here declare an `auto_map` whose targets live in a *separate* repo — for example
`jinaai/jina-embeddings-v2-base-en`. You can pin the model to an exact commit,
believe you have a reproducible artifact, and still have the executed code
change underneath you, because you never pinned the other repo. Prefixed
`auto_map` targets (`org/repo--module.Class`) are the signal; the
`remote_code_external` field flags them.

**17% of these models cannot be licence-cleared by a machine.** Not because the
terms are bad, but because the tag carries no decidable information. Any
automated licence gate has to treat them as manual review, and in practice that
means they get waved through.

## Caveats — please read before citing

- **This is still the most-scrutinised corner of the Hub.** 600 of roughly two
  million repos. Conclusions do not transfer to the full long tail, and the
  top-100-vs-tail comparison above only covers ranks up to 600.
- **Licence buckets are an engineering policy, not legal advice.** They encode
  how a commercial review would *triage* a tag. `conditional` does not mean
  "unsafe", and `permissive` does not discharge attribution duties. The mapping
  is in `license_policy.py` and is meant to be argued with.
- **Multi-licence cards resolve to the most restrictive bucket present.**
  `license: [apache-2.0, other]` is ambiguous between "take your pick" and
  "different parts, different terms"; the tag does not say which. Assuming the
  generous reading is how an automated gate ships something it shouldn't, so the
  strict reading wins. Reasonable people could argue the other way.
- **Presence of a pickle file is not evidence of malice.** Nothing here is an
  accusation about any model or author. The point is that the format offers no
  way to verify the claim either way.
- **Download counts are Hub-reported and fluctuate.** Rankings are as of the
  snapshot date.

## Method

For each model, using Hub metadata only — **no weights are downloaded**:

1. `HfApi.list_models(sort="downloads", limit=600)` for the ranking.
2. `HfApi.model_info(..., files_metadata=True)` for the revision SHA, file list
   and sizes.
3. File suffixes classify weights: `.safetensors` is safe by construction;
   `.bin`, `.pt`, `.pth`, `.pkl`, `.ckpt` unpickle on load.
4. `config.json` is fetched **at the pinned revision** and its `auto_map` read.
5. Gating comes from `ModelInfo.gated`.
6. The licence tag is classified by `license_policy.classify`.

### Three measurement mistakes worth documenting

All three produced confident, wrong output in earlier runs.

- **Looking for `.py` files to detect remote code is wrong in both
  directions.** It false-positives on training scripts that are never loaded
  (`all-MiniLM-L6-v2` ships `train_script.py`) and misses the real case entirely
  when the code lives in another repo. The deciding signal is `auto_map` in
  `config.json`, nothing else.
- **Detecting gating via an HTTP 403 does not work.** Metadata reads on gated
  repos succeed; only file downloads are blocked. That check reported 0% gated
  against models that are demonstrably gated. `ModelInfo.gated` is the signal.
- **Found only by scaling from 100 to 600:** the `config.json` fetch originally
  caught every exception and returned "no remote code", so a *throttled* request
  would have been silently recorded as a clean result — a false negative in the
  single field that matters most. Throttling now propagates and is retried with
  backoff. 15 throttle events occurred during the 600-model run, so this would
  have corrupted the headline finding.

## Fields

| Field | Description |
|---|---|
| `rank` | position in the download ranking at snapshot |
| `repo_id` | Hub model id |
| `downloads` | Hub-reported monthly downloads at snapshot |
| `status` | `ok`, or `error:<code>` |
| `revision` | commit SHA the row was observed at |
| `gated` | `false`, `"auto"` or `"manual"` |
| `license` | raw Hub licence tag (`null` if absent, list if several) |
| `license_bucket` | `permissive` / `conditional` / `non_commercial` / `unclearable` |
| `license_declared` | whether any tag was present |
| `pipeline_tag` | Hub task tag |
| `pickle_files` | pickle-format weight files found |
| `safetensors_files` | safetensors files found |
| `remote_code` | `auto_map` targets executed on load |
| `remote_code_external` | subset of the above living in a *different* repo |

## Reproduce

```bash
pip install huggingface_hub
python scripts/scan_top_models.py --limit 600 --out data/top_models.jsonl
```

No authentication required — every call is a public, read-only Hub endpoint.
Re-running resumes, so a rate-limit interruption costs only the remaining
models.

Numbers will drift as the Hub changes; compare per-row `revision` values rather
than aggregates.

## Licence

Dataset released under CC-BY-4.0. It contains only publicly available Hub
metadata.

## Author

Built by Jayant Katta ([@katta698](https://huggingface.co/katta698)) while
working out how model artifacts should be governed on the way into a cloud
production account.

Corrections welcome — particularly on the licence buckets, which are a
judgement call and are meant to be argued with.
