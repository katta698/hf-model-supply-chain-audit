# Model supply chain control on AWS — build log and evidence

Built and verified **24 October 2026** in account `684346483786`, `us-east-1`.
Torn down the same day. Everything below is real captured output, not
illustration.

**Total cost: under $0.01.** No NAT gateway, no Interface endpoints, no
compute left running.

---

## The problem

A container in a VPC calls `AutoModel.from_pretrained("org/model")`. At
startup it reaches the public internet, downloads files nobody inspected,
under a licence nobody read, and — if the model declares an `auto_map` — also
downloads and executes Python from a *third* repository.

No organisation permits this for container images. Everybody mirrors into ECR,
scans, and pins by digest. **There is no ECR for models.**

| | Containers | Models |
|---|---|---|
| Public registry | Docker Hub | Hugging Face Hub |
| Private mirror | ECR | *nothing* |
| Scanning | ECR scan, Trivy | *nothing* |
| Pinning | image digest | commit SHA, rarely used |
| Production pulls from | ECR | **the public internet** |

The [audit of 600 models](https://huggingface.co/datasets/katta698/hf-model-supply-chain-audit)
measured how much that matters: 86 of the 600 most-downloaded models ship
weights that can only be loaded by executing them, 31 execute code fetched at
load time, and 98 carry a licence no automated check can clear.

## The control

Two halves, mirroring how ECR works.

**1. Nothing enters without passing a gate.** A pipeline — not production —
resolves a model to a commit SHA, audits that exact revision, and copies it to
S3 only if it passes policy. It records what was approved, by whom, and the
SHA-256 of every file.

**2. There is no other way in.** The subnet running inference has no route to
the internet. Not a firewall rule — no route at all. The only egress is an S3
Gateway Endpoint restricted to the mirror bucket.

```
            BEFORE                                  AFTER

  container ──► internet ──► Hub          pipeline ──► Hub   (once, reviewed)
     (any model, any version,                   │
      unreviewed, every deploy)                 ▼  audit + approve
                                             S3 mirror
                                                │
                                   container ──►┘  (verified on every read)
                                   container ──► internet  ✗ no route
```

## What got built

11 Terraform resources, all free:

| Resource | Why | Cost |
|---|---|---|
| VPC `10.80.0.0/16` | isolated, no IGW | free |
| Private subnet | where inference runs | free |
| Route table, **no `0.0.0.0/0`** | **this is the control** | free |
| S3 **Gateway** Endpoint | only egress; Interface would bill ~$7/mo | **free** |
| Endpoint policy | restricts even that to one bucket | free |
| Security group, egress wide open | deliberate — see below | free |
| IAM role + policy | `GetObject` on the mirror bucket only | free |
| Lambda (prover) | demonstrates both halves | free tier |
| CloudWatch log group, 1-day retention | evidence only | free tier |
| S3 bucket, 91.6 MB | private, versioned, encrypted, lifecycle | $0.002/mo |

**The security group allows all egress to `0.0.0.0/0` on purpose.** If it were
locked down, you could not tell which control was doing the work. Leaving it
open and still having nothing escape proves the routing is the enforcement.

---

## Evidence

### 1. The gate refuses models that fail policy

```
$ python scripts/mirror_model.py facebook/esmfold_v1 --dry-run
auditing facebook/esmfold_v1
  revision  75a3841ee059df2bf4d56688166c8fb459ddd97a
  licence   mit -> permissive
  weights   0 safetensors, 1 pickle
  verdict   BLOCK
    BLOCK  pickle-only weights: loading executes the file

refusing to mirror. This is the gate doing its job.
```

```
$ python scripts/mirror_model.py jinaai/jina-embeddings-v2-base-en --dry-run
  verdict   BLOCK
    BLOCK  executes code from another repo (jinaai/jina-bert-implementation);
           pinning this revision does not pin that code
```

```
$ python scripts/mirror_model.py meta-llama/Llama-3.1-8B-Instruct --dry-run
  licence   llama3.1 -> conditional
  verdict   REVIEW
    REVIEW licence llama3.1 carries obligations
    REVIEW gated (manual): needs accepted terms and a token

needs a human. Re-run with --approve to accept and record it.
```

Exit codes are non-zero on BLOCK and un-approved REVIEW, so CI can gate on it.

### 2. An approved model is mirrored, minus what it does not need

```
$ python scripts/mirror_model.py sentence-transformers/all-MiniLM-L6-v2 \
    --bucket hf-model-mirror-684346483786-us-east-1

  revision  1110a243fdf4706b3f48f1d95db1a4f5529b4d41
  licence   apache-2.0 -> permissive
  verdict   PASS

downloading revision 1110a243fdf4
  formats   safetensors
  allowlist *.json, *.txt, *.md, *.model, *.safetensors

mirrored 12 files, 91.6 MB
```

The three pickle files, nine ONNX variants, `rust_model.ot` and
`train_script.py` are simply absent from the mirror. A consumer cannot load
them by accident because they are not there.

### 3. The route table — the control itself

```
$ aws ec2 describe-route-tables --route-table-ids rtb-09261d2142fe5f316

 Destination    | PrefixList   | State  | Target
 10.80.0.0/16   | None         | active | local
 None           | pl-63a5400a  | active | vpce-0300ed78fcac0994e
```

Two routes. Local traffic, and S3 via the gateway endpoint. **No `0.0.0.0/0`.**

```
$ aws ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values=vpc-00d0a559f841b6538 \
    --query 'length(InternetGateways)'
0

$ aws ec2 describe-nat-gateways --filter Name=vpc-id,Values=vpc-00d0a559f841b6538 \
    --query 'length(NatGateways)'
0
```

Meanwhile the security group permits everything:

```
 CIDR        | Proto
 0.0.0.0/0   | -1
```

### 4. From inside the subnet: the Hub is unreachable, the mirror is not

```
$ aws lambda invoke --function-name hf-model-mirror-prover out.json

control_holds      : True
internet_reachable : False
timing             : {'internet_probes': 24.1, 'mirror_verify': 2.2}

internet probes from inside the private subnet:
  huggingface.co             reached=False  URLError: [Errno 99] Cannot assign requested address
  cdn-lfs.huggingface.co     reached=False  URLError: [Errno 16] Device or resource busy
  pypi.org                   reached=False  URLError: [Errno 99] Cannot assign requested address

model read over the S3 gateway endpoint:
  revision               1110a243fdf4706b3f48f1d95db1a4f5529b4d41
  approved_at            2026-10-24T14:27:29.037620+00:00
  verdict_at_approval    PASS
  pickle_files_excluded  3
  files_checked          12
  bytes                  91617680
  integrity_ok           True
```

### 5. Tampering is caught

Flip a single byte after download and before verification:

```
$ python scripts/verify_mirror.py --bucket ... --tamper-test

  TAMPER TEST: flipped one byte in vocab.txt

verifying checksums (outbound network now disabled)
  MISMATCH vocab.txt
    expected 07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3
    actual   ddc00f43783510ecd7c2f6e63871274b98bd087ee5e0db7cba67142e48aa5c60

FAILED: 1 file(s) do not match the approved manifest.
A container would refuse to start here.

$ echo $?
1
```

---

## What went wrong while building it

These are the useful part. All three were found by running the thing, not by
reasoning about it.

### A denylist of unsafe extensions leaks in both directions

The first version excluded `.bin`, `.pt`, `.pkl` and so on. Two failures:

- It waved through `rust_model.ot`, a weight format not on the list.
- It dropped `openvino_model.bin` but kept `openvino_model.xml`, leaving a
  **broken half-model** in the mirror — worse than excluding both.

Replaced with an allowlist of what is needed to serve. Formats nobody
anticipated are now absent by default rather than present by oversight.

### The mirror reflected the build machine's disk, not the policy

`snapshot_download` returns a path into a **shared cache**. The first run had
already pulled the full repo, so globbing that directory uploaded **682 MB for
a 91 MB model** — every ONNX variant included, despite the allowlist being
correct. The allowlist governed what was *fetched*, not what was *uploaded*.

A developer who had once pulled a full repo would silently widen the mirror.
Now the upload set is computed from the repo's file list filtered by the
allowlist, and a missing file is an error rather than a smaller upload.

### Versioning hid 1.36 GB of billing

The bucket is versioned so the audit trail cannot be rewritten. But deleting
the two bloated attempts left their bytes as non-current versions:

```
current         91.6 MB
non-current   1363.7 MB  <- still billed, invisible to `aws s3 ls`
```

Fifteen times the visible data. Trivial at $0.03/month; at real model sizes
this is how a mirror bucket quietly becomes the largest line on the bill.
Buckets now get a lifecycle rule expiring non-current versions after 7 days
and aborting incomplete multipart uploads after 1.

### Lambda timed out, and not for the reason I assumed

First invocation hit the 30s timeout. I assumed hashing 91 MB at 256 MB of
memory was too slow — Lambda CPU scales with memory. Raising it to 1024 MB cut
verification to **2.2s**, so that was real, but the actual culprit was the
internet probes taking **24.1s for three attempts**. `urlopen(timeout=3)`
does not cover DNS resolution, so each probe spent ~8s in `getaddrinfo`
before the socket timeout could apply. Failing fast on a blackholed route
needs the DNS timeout handled separately.

---

## Rebuild

```bash
# 1. Mirror an approved model (creates the bucket on first run)
python scripts/mirror_model.py sentence-transformers/all-MiniLM-L6-v2 \
    --bucket hf-model-mirror-<account>-us-east-1 --create-bucket

# 2. Verify from the consumer side
python scripts/verify_mirror.py --bucket hf-model-mirror-<account>-us-east-1 \
    --repo-id sentence-transformers/all-MiniLM-L6-v2

# 3. Network control
cd terraform
terraform init
terraform apply -var bucket_name=hf-model-mirror-<account>-us-east-1

# 4. Prove it
aws lambda invoke --function-name hf-model-mirror-prover out.json && cat out.json
```

## Teardown

```bash
cd terraform && terraform destroy -auto-approve
python scripts/teardown.py --bucket hf-model-mirror-<account>-us-east-1 --yes
```

The bucket is versioned, so `teardown.py` removes every version and delete
marker — deleting objects alone leaves a bucket that will not drop and keeps
billing for storage you cannot see.

## What this does not cover

- **One region, one account.** Multi-region means replicating the bucket and
  an endpoint per region; multi-account means a shared mirror plus
  cross-account bucket policy.
- **It is a gate, not a monitor.** A model approved today is not re-checked
  when its licence changes upstream.
- **Gated repos** need a credentialed token in the pipeline, which is its own
  secret to manage.
- **No story for models that legitimately need remote code.** They are
  currently BLOCK if the code lives elsewhere, which is correct but blunt.
- **Storage grows with every version.** The lifecycle rule bounds non-current
  versions, not the number of approved revisions.
