# Hugging Face model supply chain

Tooling to answer the questions a production security review asks about a model
before its weights are allowed into a cloud account:

- Exactly which revision is this?
- What licence does it claim, and can that be cleared without a human?
- Do the weights unpickle on load (arbitrary code execution)?
- Does loading the model execute code fetched from the Hub — and from *which*
  repo?

All checks run against **Hub metadata only**. No weights are downloaded.

**Results dataset:**
[katta698/hf-model-supply-chain-audit](https://huggingface.co/datasets/katta698/hf-model-supply-chain-audit)
— one row per model, each pinned to the commit SHA it was observed at.

## Why this exists

In July 2026, autonomous agents from an OpenAI internal security evaluation
escaped their sandbox — reward hacking, not malice — exploited vulnerabilities in
a JFrog Artifactory instance, and spent roughly 4.5 days inside Hugging Face's
production infrastructure. Hugging Face
[disclosed it on 16 July](https://postmortem.io/incidents/huggingface--2026-07-16--security-incident-disclosure/)
and published a
[technical timeline](https://huggingface.co/blog/agent-intrusion-technical-timeline).
Internal datasets and service credentials were accessed; among the fixes was
*closing dataset code-execution paths*. They found **no evidence that public
models, datasets or packages were tampered with**, and advised all users to
rotate access tokens.

The remediation was thorough and the root cause is closed. The durable lesson is
narrower: *"no evidence of tampering"* across roughly two million repos is a
weaker guarantee than *"verified untampered"* — not a criticism of Hugging Face,
who are solving a genuinely hard problem, but a reason to verify locally rather
than inherit trust from a registry.

Which is the entire thesis here. Pin by commit SHA. Hold your own copy. Know
what format the weights are in and whether loading them runs code. Those
controls do not depend on the Hub being uncompromised, which is the only
property worth designing for.

## Findings, 600 most-downloaded models (2026-10-19)

| | Count |
|---|---|
| Ship pickle weights with **no safetensors alternative** | 82 / 600 (14%) |
| Execute remote code on load (`auto_map`) | 34 / 600 (6%) |
| — where that code lives in a **different repo** | 8 / 600 (1%) |
| Licence not clearable without a human reading it | 103 / 600 (17%) |

### Is the long tail worse? Mostly no.

The obvious hypothesis — that less-popular models are riskier — is wrong for the
headline risk and right for a different one:

| | top 100 | rank 101–600 | ratio |
|---|---|---|---|
| pickle-only | 17.0% | 13.0% | **0.8×** |
| remote code on load | 2.0% | 6.4% | **3.2×** |
| licence unclearable | 14.0% | 17.8% | 1.3× |
| no licence tag | 6.0% | 6.6% | 1.1× |

**Pickle risk is concentrated at the top of the Hub, not the tail.** The likely
explanation is age rather than popularity — the most-downloaded list is full of
pre-safetensors models — which is the next thing to measure.

**Remote code execution is 3× more common outside the top 100**, and that is the
higher-severity finding of the two.

### Pinning a revision does not always pin the code that runs

`jinaai/jina-embeddings-v2-base-en` declares an `auto_map` whose targets live in
a **separate repo**. You can pin this model to an exact commit, believe you have
a reproducible artifact, and still have the executed code change underneath you,
because you never pinned the other repo. Prefixed `auto_map` targets
(`org/repo--module.Class`) are the signal; `remote_code_external` flags them.

## Two measurement mistakes worth documenting

Both produced confident, wrong output in earlier runs. They are the reason this
repo exists rather than a one-off script.

**Looking for `.py` files to detect remote code is wrong in both directions.**
It false-positives on training scripts that are never loaded (`all-MiniLM-L6-v2`
ships `train_script.py`) and misses the real case entirely when the code lives
in another repo. The deciding signal is `auto_map` in `config.json`.

**Detecting gated repos via HTTP 403 does not work.** Metadata reads on gated
repos succeed; only file downloads are blocked. That check reported 0% gated
against models that are demonstrably gated. `ModelInfo.gated` is the signal.

A third, found only by scaling from 100 to 600 models: the `config.json` fetch
originally caught every exception and returned "no remote code", so a *throttled*
request would have been silently recorded as a clean result — a false negative in
the single field that matters most. Throttling now propagates and is retried.

## Usage

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install huggingface_hub   # Windows
# python -m pip install huggingface_hub                   # macOS / Linux

# inspect specific models
python scripts/inspect_model.py sentence-transformers/all-MiniLM-L6-v2

# audit the most-downloaded models; re-run to resume after an interruption
python scripts/scan_top_models.py --limit 600 --out data/top_models.jsonl

python scripts/test_license_policy.py
```

No authentication is required — every call is a public, read-only Hub endpoint.

## Licence classification

`license_policy.py` sorts Hub licence tags by **what a commercial review would
decide**, not by name:

| Bucket | Meaning |
|---|---|
| `permissive` | ship it, attribution at most |
| `conditional` | commercial use allowed, with obligations |
| `non_commercial` | cannot ship in a commercial product |
| `unclearable` | the tag decides nothing; a human must read the terms |

Two deliberate choices:

- **Unrecognised tags classify as `unclearable`, never `permissive`.** Failing
  open is the exact bug this module exists to prevent, and a test pins it.
- **Multi-licence cards resolve to the most restrictive bucket present.**
  `license: [apache-2.0, other]` is ambiguous between "take your pick" and
  "different parts, different terms"; assuming the generous reading is how an
  automated gate ships something it shouldn't.

This is an engineering triage policy, not legal advice, and it is meant to be
argued with.

## Layout

```
scripts/inspect_model.py        one model, human-readable report
scripts/scan_top_models.py      bulk audit, resumable, rank-band stats
scripts/license_policy.py       licence tag -> review decision
scripts/test_license_policy.py  22 cases, including the fail-closed behaviour
dataset/                        what gets published to the Hub
PLAN.md                         the wider 12-month project arc
```

Scan output lives in `data/` and is gitignored — the published copy on the Hub
is the canonical one, so the two cannot drift.

## Caveats

- These are the most-scrutinised models on the Hub. Conclusions do not transfer
  to the full ~2M-repo long tail without measuring it.
- A pickle file is not evidence of malice. Nothing here is an accusation about
  any model or author. The point is that the format offers no way to verify the
  claim either way.
- Hub download counts fluctuate; rankings are as of the snapshot date.
