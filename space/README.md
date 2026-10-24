---
title: Model Supply Chain Review
emoji: 🔍
colorFrom: indigo
colorTo: gray
sdk: static
app_file: index.html
pinned: true
license: apache-2.0
short_description: What a security review should ask about a HF model
tags:
  - supply-chain
  - security
  - model-governance
  - licensing
  - mlops
---

# Model supply chain review

Paste a Hugging Face model id and get back what a production security review
would ask about it **before its weights enter a cloud account**:

- Is the revision pinned, and what is it?
- Do the weights unpickle on load — and is there a safetensors alternative?
- Does loading execute code fetched from the Hub, and from *which* repo?
- Can the declared licence be cleared without a human reading it?
- Is the repo gated, so CI needs a credentialed token?

Findings are graded against the **600 most-downloaded models on the Hub**, so
the output says not just *what* a model does but *how unusual that is*.

**Runs entirely in your browser.** Every request goes straight from you to the
Hub; there is no server, nothing is logged, and the page never sleeps. Metadata
only -- no weights are downloaded.

## Verdicts

| | Meaning |
|---|---|
| 🟢 PASS | safetensors, permissive licence, no remote code |
| 🟠 REVIEW | something a human has to decide — unclearable licence, remote code |
| 🔴 BLOCK | cannot be mitigated by configuration — pickle-only weights, non-commercial licence, or code loaded from a repo you cannot pin |

## The finding worth knowing about

Some models declare an `auto_map` whose targets live in a **different repo**.
You can pin such a model to an exact commit SHA, believe you have a
reproducible artifact, and still have the executed code change underneath you,
because you never pinned the other repo. Around 1% of the most-downloaded
models do this. Try `jinaai/jina-embeddings-v2-base-en`.

## Caveats

- A pickle file is **not** evidence of malice. Nothing here is an accusation
  about any model or author. The point is that the format offers no way to
  verify the claim either way.
- Licence buckets are an **engineering triage policy, not legal advice**, and
  are meant to be argued with. Multi-licence declarations resolve to the most
  restrictive bucket present.
- The baseline is a point-in-time snapshot; the per-model review is live.

## Links

- **Dataset:** [katta698/hf-model-supply-chain-audit](https://huggingface.co/datasets/katta698/hf-model-supply-chain-audit)
- **Code:** [github.com/katta698/hf-model-supply-chain-audit](https://github.com/katta698/hf-model-supply-chain-audit)

Built by Jayanth Katta ([@katta698](https://huggingface.co/katta698)).
