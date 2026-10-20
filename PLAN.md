# 12-month plan: open-weight models in production, across three clouds

Written 2026-10-19. Revisit quarterly; expect to change at least one project.

## The positioning this is building toward

> I take open-weight models and make them production systems in any of the three
> major clouds — and I can tell you what that will cost, how it behaves at p99,
> and when you should use a managed API instead.

That sentence is the whole point. Every project below is chosen because it makes
one clause of it defensible. It is deliberately **not** "ML engineer" — that race
is crowded and starts from a different background. It is solutions architecture
applied to a workload type most architects cannot cost or capacity-plan.

Three things make it credible rather than aspirational:

1. **Measured numbers, not opinions.** Every project ends in a number someone
   could challenge and a method they could re-run.
2. **Negative results published.** "Don't self-host this" and "fine-tuning lost
   to a better prompt" are the findings that separate an architect from an
   enthusiast.
3. **Genuine multi-cloud, used selectively.** Only where the clouds actually
   differ. Repeating identical plumbing three times proves nothing.

## Principles

- **One project at a time.** Six finished beats twelve started.
- **Projects compound.** Each reuses the previous one's artifact. By month 12
  there is one coherent body of work, not six unrelated repos.
- **One publishable artifact each** — dataset, repo, or benchmark — plus one
  honest post. The post carries the number; the artifact carries the evidence.
- **Multi-cloud only in P2, P3 and P6.** Elsewhere it is busywork.
- **Teardown script in the same commit as the create script.** Not after.
- **A budget alarm before the first GPU**, every time.

## The projects

### P1 — Model supply chain control (months 1–2) · ~$5

**Status: audit half is done and published.**
[katta698/hf-model-supply-chain-audit](https://huggingface.co/datasets/katta698/hf-model-supply-chain-audit)

Turn the audit into an actual control. Mirror a pinned model revision into S3,
scan it (safetensors enforcement, pickle detection, `auto_map` remote-code
detection), gate the licence, write a provenance manifest, and deny egress to
the Hub from inference subnets. Ship it as a Terraform module.

Finish the audit first: test whether pickle risk tracks model **age** rather
than popularity. The 600-model scan showed the top 100 are *worse* than the tail
for pickle (17% vs 13%) — age is the likely explanation and it is one API field
away from being measured.

- **Demonstrates:** guardrails, IaC, artifact governance. Squarely existing
  strengths applied to a new artifact class, with almost no competition.
- **Fails at scale:** gated repos needing per-user tokens; storage cost across
  many multi-GB versions and regions; it is a one-time gate, not continuous
  monitoring; no answer for models that legitimately need remote code.
- **Durable skill:** model provenance and supply chain. Ages extremely well.
- **Later:** port the module to Azure and GCP in P6. Cheap, and makes the
  multi-cloud claim concrete.

### P2 — Inference economics benchmark, three clouds (months 3–4) · ~$60–150

The differentiator project. Serve the **same two models** (one embedding model,
one 7–8B generative) with the **same stack** (TEI and vLLM) on AWS, Azure and
GCP. Measure tokens/sec and p50/p99 at concurrency 1/4/16/64. Derive
cost-per-million-tokens as a function of utilisation. Then compare against the
managed per-token APIs: Bedrock, Azure AI Foundry, Vertex.

Publish the crossover curves: at what utilisation does self-hosting start to win,
and on which cloud.

- **Why anyone cares:** this is the question in every architecture review, and
  nobody brings numbers.
- **Demonstrates:** capacity planning, cost modelling, load testing, and real
  multi-cloud. Almost nobody can produce this because almost nobody has all
  three clouds.
- **Fails at scale:** single-region; ignores Savings Plans / reservations /
  committed use discounts; prefix caching and speculative decoding break the
  linear cost model; spot interruption not modelled.
- **Durable skill:** the most durable on this list. Inference economics will
  outlive every model named in it.
- **Cost control:** use GCP's trial credit and Azure's free credit for two of
  the three legs. Spot/preemptible throughout. Expect the AWS leg to be the
  only real spend.

### P3 — One real workload, end to end, with a quality number (months 5–6) · ~$20–40

Pick **one** domain — audio or documents — and do it properly. Audio version:
Whisper self-hosted vs Transcribe vs Azure Speech vs Google STT. Batch pipeline
over a public dataset, cost per 1,000 hours, **and word error rate measured on
the same audio for all four.**

The quality number is the point. Cost comparisons without a quality baseline are
the most common lie in this space.

- **Demonstrates:** evaluation discipline, pipeline engineering, and the
  judgement to hold quality constant before comparing price.
- **Fails at scale:** WER on a public dataset does not predict WER on your
  domain audio; no speaker diarization; batch latency unacceptable for
  interactive use.
- **Durable skill:** evaluation. "Cheaper is meaningless without a quality
  number" is the single most reusable sentence you will learn this year.

### P4 — Fine-tuning economics, including the negative result (months 7–8) · ~$30–60

LoRA fine-tune a small model for one narrow task. Compare against prompting a
frontier model on the same task: accuracy, cost per million inferences, build
time, and maintenance burden. **Publish it even if prompting wins** — especially
if prompting wins.

Then deploy the artifact three ways to learn the import paths: Bedrock Custom
Model Import, Azure ML endpoint, Vertex endpoint. Document where each refuses
the model and why.

- **Demonstrates:** when *not* to fine-tune; owning your own weights; the
  managed-import paths and their architecture allowlists.
- **Fails at scale:** no retraining loop as data drifts; eval set goes stale;
  Custom Model Import cold starts and per-unit pricing when kept warm.
- **Durable skill:** fine-tuning economics, LoRA/QLoRA, and the discipline to
  publish a result that undercuts your own project.

### P5 — Production-shaped serving and autoscaling (months 9–10) · ~$50–100

Multi-model serving on Kubernetes — EKS, then AKS or GKE — with vLLM,
autoscaling on queue depth rather than CPU, and scale-to-zero. Add a **cascade**:
route to a small model first, escalate to a large one only on low confidence.
Load test with a realistic traffic profile, not a flat RPS.

- **Demonstrates:** the serving stack, GPU autoscaling (genuinely hard and
  rarely done well), and cascade routing. The most senior-looking project here.
- **Fails at scale:** GPU node cold start measured in minutes, so scale-to-zero
  trades cost for tail latency; cascade savings erode as the escalation rate
  creeps up; multi-tenant KV cache pressure.
- **Durable skill:** continuous batching, GPU autoscaling, cascade design.

### P6 — Synthesis: the reference architecture (months 11–12) · ~$0

Pull all of it into one published reference architecture — *running open-weight
models in a regulated enterprise, across three clouds* — plus a decision
framework: when a managed API, when self-host, when fine-tune, and when not to
use Hugging Face at all. Port the P1 guardrail module to Azure and GCP so the
multi-cloud claim is backed by code.

This is the artifact that reads as architect-level rather than engineer-level,
because it is about judgement rather than implementation. Aim it at a conference
talk or a long-form write-up.

- **Durable skill:** the decision framework itself, which is what gets you hired
  as an architect rather than an implementer.

## Budget

| Project | Estimate |
|---|---|
| P1 | $5 |
| P2 | $60–150 |
| P3 | $20–40 |
| P4 | $30–60 |
| P5 | $50–100 |
| P6 | $0 |
| **Total** | **$165–355 over 12 months** |

Honest note: this is well above the current $20 cap. Roughly $15–30/month if
spread evenly, and GCP and Azure trial credits can absorb a meaningful share of
P2 and P4. If the cap has to hold, P1, P3 and P6 are achievable nearly in full;
P2 and P5 are the ones that genuinely need GPU hours and cannot be faked
honestly. **Simulated benchmarks are worse than no benchmarks** — do not publish
modelled numbers as if they were measured.

## What to deliberately skip

- RAG chatbot demos. Everyone has one; it signals nothing.
- Agent frameworks as a project topic. The churn is faster than your publishing
  cadence.
- Anything whose artifact is a notebook ending in `predictor.predict()`.
- JumpStart / Studio clickops. Knowing the wrapper is not the skill.
- Re-uploading or forking models to pad the HF profile. Immediately visible.

## On certifications

These projects are worth more than another cert for this particular goal,
because the gap in the market is demonstrated judgement rather than credentials.
If credentials are wanted anyway, the ML specialty exams across the three clouds
map closely onto P3–P5 and are much easier after doing the work than before.

## Cadence

- One project per two months, finished and published before the next starts.
- One post per project, carrying the number.
- Revisit this file every quarter. If a project no longer looks valuable, cut it
  rather than finishing it out of obligation.
