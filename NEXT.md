# Where things stand — 22 Oct 2026

## Done

The audit half of P1 is finished and published.

- **Dataset:** https://huggingface.co/datasets/katta698/hf-model-supply-chain-audit
- **Code:** https://github.com/katta698/hf-model-supply-chain-audit

600 models audited. Main findings: 82 ship weights that can only be loaded
unsafely, 34 execute code fetched at load time, 8 of those load it from a
*different* repo, and 103 carry licences no automated check can clear.

The best result is the age analysis: pickle risk fell from 40.6% of 2022 repos
to 0.5% of 2026 repos, while remote-code execution went from 0% in 2022 to a
13.2% peak in 2024. **The ecosystem fixed the weight-format problem and
introduced a different one in its place.**

Total spend so far: **$0.** Nothing has touched AWS.

## Not done

- The LinkedIn post is drafted but not posted (in chat history, 22 Oct).
- The AWS control — the second half of P1.

## Next session: start by understanding the control, not building it

The thing to be clear on before any code gets written:

**The problem.** Today, a container in your account can call
`from_pretrained("someone/some-model")` at deploy time. That reaches out to the
internet, pulls files nobody inspected, and may execute code from a repo you
never pinned. There is no gate.

**The control, in four steps:**

1. **Copy, don't fetch.** Download a specific model *revision* (a commit SHA,
   not `main`) once, deliberately, and store it in your own S3 bucket.
2. **Scan it on the way in.** Reuse the checks already built: is it safetensors
   or pickle, does `config.json` declare `auto_map`, what licence does it carry?
   Reject anything that fails policy.
3. **Record what you approved.** A manifest saying "this model, this SHA, these
   findings, approved on this date" — so the question "what is running and where
   did it come from" has an answer.
4. **Close the back door.** Deny network egress to `huggingface.co` from the
   subnets that run inference. If the only path to a model is your bucket, the
   gate cannot be bypassed by someone in a hurry.

**Why it matters:** steps 1 and 4 are the ones that hold even if the Hub itself
is compromised, which is the only property worth designing for.

**Cost:** about $1. S3 storage, a Lambda, no GPU.

**AWS pieces involved:** S3, Lambda, IAM, a VPC endpoint policy or SCP, and
Terraform to tie it together. All familiar ground — the only new part is *what*
is being governed.

### Open question for next time

Whether to build this as a Terraform module (reusable, portfolio-friendly) or as
a plain script first (faster to understand, easier to explain). Recommendation:
script first, Terraform once the logic is proven.
