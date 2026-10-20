# Working rules for this project

## Verify before asserting — not optional

Training data has a **May 2026 cutoff**. Anything time-sensitive must be checked
with a web search *before* it goes in a reply, a lab, a plan or a cost estimate.
Do not answer from memory and offer to verify afterwards; verify first, then
answer.

Standing instruction from the user (2026-10-19), after I described the July 2026
Hugging Face security incident as something I was unaware of:

> "When providing the labs or any suggestions, make sure you fetch the latest
> data at any point of time. I don't have to repeat this again."

**Always search before stating:**

- Cloud pricing of any kind — instance rates, per-token, per-minute, per-page
- Service capabilities and limits (what Bedrock / Azure AI Foundry / Vertex
  currently support, supported architectures for model import, quotas)
- Which models exist, their sizes, and their licence terms
- Security incidents, CVEs, advisories
- API surfaces and SDK behaviour — these churn fast (`huggingface_hub` 2.x had
  already dropped `direction` from `list_models`, and `ModelInfo.gated` replaced
  what an older guide would have told you to do)
- Anything described as "current", "latest", "now supports" or "as of"

**Safe to answer from memory:** concepts that don't move — GPU memory math,
batching and KV cache behaviour, the shape of a cost model, IR/retrieval
fundamentals, why pickle is unsafe.

**When a search can't confirm something, say so explicitly** rather than
smoothing over the gap. "I couldn't verify this" is a usable answer; a confident
wrong number is not.

## Known-stale claims to re-verify

Asserted from training data before this rule existed. Treat as unverified:

- GPU instance hourly rates quoted for `g5`, `inf2` and spot equivalents
- Hugging Face Pro / GPU Space pricing
- Bedrock Custom Model Import's supported architecture list and pricing model
- The AWS-service-to-HF-model mapping table in `README.md` discussions
- All cost estimates in `PLAN.md`

## Project conventions

- **One project at a time**, finished and published before the next starts.
- **Flag real money before it is spent**, with a number. Standing cap is low; see
  the budget section of `PLAN.md` for where that bites.
- **Teardown script in the same commit as the create script.**
- **Blunt over encouraging.** Say when something is harder than it looks, and say
  when the right answer is "don't use Hugging Face for this."
- **Publish negative results.** A disproven hypothesis is the finding.
- Measured numbers only. Never present a modelled number as a measured one.

## Audience

The user is an AWS platform engineer / solutions architect who also works across
Azure and GCP, learning this ecosystem to build a public portfolio. Not an ML
engineer and not trying to become one. Explain in small increments; a long
up-front landscape dump does not land.
