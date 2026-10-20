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
        path: top_100.jsonl
---

# Supply-chain audit of the 100 most-downloaded Hugging Face models

A point-in-time audit of the top 100 models on the Hub by monthly downloads,
recording the things a production security review would ask about: pinned
revision, weight file format, whether loading the model executes code fetched
from the Hub, gating, and whether the declared licence can be cleared without a
human reading it.

Snapshot taken **2026-10-19**. Every row carries the commit SHA it was observed
at, so any claim here can be re-checked against that exact revision.

## Findings

| Property | Count |
|---|---|
| Ships at least one pickle-format weight file | 50 / 100 |
| **Ships pickle with no safetensors alternative** | **17 / 100** |
| Executes remote code on load (`auto_map`) | 2 / 100 |
| — where that code lives in a *different* repo | 1 / 100 |
| Gated (requires token + accepted terms) | 5 / 100 |

Licence, bucketed by what a commercial review would actually decide:

| Bucket | Meaning | Count |
|---|---|---|
| `permissive` | ship it, attribution at most | 81 / 100 |
| `conditional` | commercial use allowed, with obligations | 3 / 100 |
| `non_commercial` | cannot ship in a commercial product | 2 / 100 |
| `unclearable` | tag decides nothing; a human must read the terms | 14 / 100 |

Of the `unclearable` group, 6 declare no licence at all and 8 declare `"other"`.

## What's actually interesting here

**The pickle number that matters is 17, not 50.** Half the list ships a
pickle file, but most of those also ship safetensors — you can simply load the
safe one. For 17 of the top 100 there is no safe option: using the model means
unpickling, which means executing whatever is in the file. No flag avoids it.

**Pinning a revision does not necessarily pin the code that runs.** One model in
this set (`jinaai/jina-embeddings-v2-base-en`) declares an `auto_map` whose
targets live in a *separate* repo. You can pin this model to an exact commit,
believe you have a reproducible artifact, and still have the executed code
change underneath you — because you never pinned the other repo. Prefixed
`auto_map` targets (`org/repo--module.Class`) are the signal, and the
`remote_code_external` field flags them.

**14% of the most popular models on the Hub cannot be licence-cleared by a
machine.** Not because the terms are bad, but because the tag carries no
decidable information. Any automated licence gate has to treat these as manual
review, and in practice that means they get waved through.

## Caveats — please read before citing

- **This is the most-scrutinised corner of the Hub.** These are the top 100 by
  downloads: mostly major labs, with many eyes on them. The long tail is
  plausibly worse, but that is **not measured here** and should not be inferred.
- **Remote code execution is rare in this sample (2%).** It is the
  scariest-sounding finding and it is genuinely uncommon at the top of the Hub.
  The interesting part is not its frequency but that the obvious detection
  method misses it (see below).
- **Licence buckets are an engineering policy, not legal advice.** They encode
  how a commercial review would *triage* a tag. `conditional` does not mean
  "unsafe" and `permissive` does not discharge attribution duties. The mapping
  is in `license_policy.py` and is meant to be argued with.
- **Presence of a pickle file is not evidence of malice.** Nothing here is an
  accusation about any model or author. The point is that the format offers no
  way to verify the claim either way.
- **Download counts are Hub-reported and fluctuate.** Ranking is as of the
  snapshot date.

## Method

For each model, using Hub metadata only — **no weights are downloaded**:

1. `HfApi.list_models(sort="downloads", limit=100)` for the ranking.
2. `HfApi.model_info(..., files_metadata=True)` for the revision SHA, file list
   and sizes.
3. File suffixes classify weights: `.safetensors` is safe by construction;
   `.bin`, `.pt`, `.pth`, `.pkl`, `.ckpt` unpickle on load.
4. `config.json` is fetched **at the pinned revision** and its `auto_map` read.
5. Gating comes from `ModelInfo.gated`.
6. The licence tag is classified by `license_policy.classify`.

### Two measurement mistakes worth documenting

Both of these produced confidently wrong output in earlier runs:

- **Looking for `.py` files to detect remote code is wrong in both
  directions.** It false-positives on training scripts that are never loaded
  (`all-MiniLM-L6-v2` ships `train_script.py`), and it misses the real case
  entirely when the code lives in another repo. The deciding signal is
  `auto_map` in `config.json`, nothing else.
- **Detecting gating via an HTTP 403 does not work.** Metadata reads on gated
  repos succeed; only file downloads are blocked. That check reported 0% gated
  against models that are demonstrably gated. `ModelInfo.gated` is the signal.

## Fields

| Field | Description |
|---|---|
| `repo_id` | Hub model id |
| `downloads` | Hub-reported monthly downloads at snapshot |
| `status` | `ok`, or `error:<code>` |
| `revision` | commit SHA the row was observed at |
| `gated` | `false`, `"auto"` or `"manual"` |
| `license` | raw Hub licence tag (`null` if absent) |
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
python scripts/scan_top_models.py --limit 100 --out data/top_models.jsonl
```

Numbers will drift as the Hub changes; compare per-row `revision` values rather
than aggregates.

## Licence

Dataset released under CC-BY-4.0. It contains only publicly available Hub
metadata.

## Author

Built by Jayant Katta ([@katta698](https://huggingface.co/katta698)) while
working out how model artifacts should be governed on the way into an AWS
production account.

Corrections welcome — particularly on the licence buckets, which are a
judgement call and are meant to be argued with.
