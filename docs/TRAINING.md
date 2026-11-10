# Urai Training Guide

How to improve Urai's model: from generating training data on your box to
running the fine-tune on a free GPU and deploying the result.

**No GPU on the server is fine.** The server generates and verifies data;
free cloud GPUs (Kaggle T4) do the actual training.

---

## The pipeline at a glance

```
[This box]                        [Free cloud GPU]
  │                                      │
  ▼                                      │
Generate tasks                           │
  ↓                                      │
Teacher generates answers                │
  ↓                                      │
Verify + filter                          │
  ↓                                      │
data/verified/distill-vX.jsonl ──────── ▶ QLoRA fine-tune (Kaggle T4, ~15 min)
                                          │
                                          ▼
                                     adapter/ folder
                                          │
[Back on this box] ◀────────────────────-┘
  │
  ▼
Merge adapter → GGUF export
  ↓
urai model bench (must beat current best)
  ↓
urai model use <new-model>
  ↓
Restart + done
```

---

## Stage 0 — Few-shot promotion (live now, zero effort)

Every verified chunk **already improves answers** without retraining.
`scripts/distill/promote_chunk.py` moves verified completions into
`data/prompts/fewshots.jsonl`. The agent (`jev/fewshots.py`) injects
top-matching examples for level ≥ 1 tasks automatically.

Nothing to do here — it runs in CI on every commit that adds
`data/verified/*.jsonl` files.

---

## Stage 1 — Grow the dataset (do this regularly)

### 1a. Generate tasks + teacher answers

```bash
cd /opt/urai   # or your local repo

# Generate new task prompts (seeds new categories automatically)
python3 scripts/distill/generate_tasks.py --seed $(date +%s) \
  --out data/raw_tasks/batch-$(date +%Y%m%d).jsonl

# Run teacher (uses local model by default; set env vars for cloud teacher)
export TEACHER_BASE_URL=http://127.0.0.1:8777/v1
export TEACHER_API_KEY=$URAI_MASTER_KEY
export TEACHER_MODEL=urai

python3 scripts/distill/run_distill.py \
  --tasks data/raw_tasks/batch-$(date +%Y%m%d).jsonl \
  --out   data/verified/distill-$(date +%Y%m%d).jsonl \
  --report eval/reports/distill-$(date +%Y%m%d).json \
  --system reasoning --exec --judge
```

What `--exec --judge` does:
- `--exec`: runs Python code blocks to verify they execute without error
- `--judge`: scores completions; rejects anything below threshold 0.8
- Secrets are scanned before writing — leaked tokens/keys auto-fail

### 1b. Automated grind (runs on the VPS via Actions)

The weekly self-improve workflow (`.github/workflows/urai-selfimprove.yml`)
probes the live API, finds failures, and mines them into new tasks automatically.
It commits the new `data/raw_tasks/selfimprove/*.jsonl` files every Sunday at 03:00 UTC.

No action needed — just make sure `URAI_MASTER_KEY` and `URAI_BASE_URL`
are set as GitHub Actions secrets/variables.

### Target before training

Aim for **≥ 1,000 verified examples** with think traces in
`data/verified/` before spending GPU time. 200 rows produces a detectable
improvement; 2,000+ is where it becomes clearly measurable.

Check current count:
```bash
cat data/verified/*.jsonl | wc -l
```

---

## Stage 2 — Fine-tune on Kaggle (free, ~15 min)

### 2a. Pack the dataset

```bash
python3 scripts/train/pack_dataset.py \
  --inputs data/verified/distill-*.jsonl \
  --out /tmp/urai-train-data.tar.gz
```

### 2b. Upload to Kaggle as a dataset

1. Go to [kaggle.com/datasets](https://www.kaggle.com/datasets) → **New Dataset**
2. Upload `/tmp/urai-train-data.tar.gz`
3. Name it `urai-distill-vX` — note the dataset slug (e.g. `yourusername/urai-distill-vX`)

### 2c. Run the training notebook

1. Go to [kaggle.com](https://www.kaggle.com) → **New Notebook**
2. Settings → **GPU T4 x2** (free tier, 30 GPU-hours/week)
3. Add your dataset as an input (the slug from step 2b)
4. Paste and run `notebooks/train_urai_qlora.ipynb` (copy it cell by cell or upload)

The notebook trains Qwen3-0.6B (or 4B) with QLoRA (`r=16`, `alpha=16`,
4-bit, ~15 min on T4×2) and pushes the adapter to HuggingFace Hub
(`tukitattu/urai-<tag>`).

### 2c-alt. GitHub Actions dispatch (needs a GPU runner)

```bash
# Dispatch from CLI (requires GPU runner configured in the repo)
gh workflow run urai-train.yml \
  --field tag=distill-$(date +%Y%m%d) \
  --field base=Qwen/Qwen3-4B
```

Without a GPU runner this will warn and exit — that's intentional.
Use the Kaggle notebook path above for free training.

---

## Stage 3 — Bring the adapter home + export GGUF

### 3a. Download the adapter from HuggingFace

```bash
pip install huggingface_hub
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('tukitattu/urai-distill-v1', local_dir='model/adapters/urai-v1')
"
```

### 3b. Merge adapter + export GGUF

Requires the Unsloth environment (easiest on the Kaggle notebook itself,
or a local GPU box). The training script prints the exact export commands
at the end of the run:

```bash
# On the GPU machine (Kaggle terminal or Colab):
python3 - <<'EOF'
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained("model/adapters/urai-v1")
model.save_pretrained_gguf("model/base/urai-v1", tokenizer,
                           quantization_method="q4_k_m")
EOF
```

Download the resulting `urai-v1-Q4_K_M.gguf` to `model/base/` on your server.

### 3c. Register the model

```bash
urai model add urai-v1 model/base/urai-v1-Q4_K_M.gguf
```

---

## Stage 4 — Benchmark gate (must pass before activating)

Never activate a new model without running the bench. A regression means
the training data had quality issues — discard and grow more data.

```bash
# Benchmark the candidate
urai model bench --id urai-v1

# Compare against the current active model
python3 scripts/student_baseline.py --model urai-v1 --n 20
# Compare mean_score in eval/reports/student-baseline-urai-v1.json
# vs eval/reports/student-baseline-<current>.json
# Higher mean wins. On a tie, smaller/faster wins.
```

Bench must not regress on: knowledge, math, code, and harness probes.
If it passes:

```bash
urai model use urai-v1
systemctl restart urai-api     # on the VPS
```

---

## Inference speed improvements (no training needed)

These are free gains on the existing model:

| Technique | Command | Expected gain |
|---|---|---|
| Ngram speculative decoding | `urai serve start --spec ngram-mod` | 1.2–1.6× decode |
| KV-cache quantization | Default on: `-ctk q8_0 -ctv q8_0` | Less RAM, often faster |
| IQ4_XS quantization | Download IQ4_XS GGUF instead of Q4_K_M | Smaller + faster |
| Flash Attention | Auto-enabled when supported | Faster prefill |

Benchmark after each change and record in `eval/reports/`.

---

## Better base models (drop-in swap, no training)

Any GGUF can replace the active model. Tested options:

| Model | Size on disk | Notes |
|---|---|---|
| `qwen3-06b` Q8_0 | ~0.7 GB | Fast, good for simple tasks |
| `qwen3-17b` Q4_K_M | ~1.1 GB | Best 1–2B class open model |
| `qwen3-4b` Q4_K_M | ~2.3 GB | Default, good balance |
| `qwen25vl-3b` | ~2.6 GB | Vision tasks (already wired) |

```bash
urai model download qwen3-17b
urai model bench --id qwen3-17b
urai model use qwen3-17b
systemctl restart urai-api
```

---

## Method: Reasoning traces (R1-style, stronger than plain SFT)

Small models gain most from learning *how to think*, not just the answer.
Use `--system reasoning` in the distill step (already shown above) to
include chain-of-thought traces in the training data.

```bash
python3 scripts/distill/run_distill.py \
  --tasks data/raw_tasks/expanded \
  --out   data/verified/distill-reasoning.jsonl \
  --system reasoning --exec --judge
# Then train on it with Stage 2 — traces ride along in the completion text
```

---

## Method: Model merging (zero GPU, sometimes +accuracy)

Merge two fine-tuned adapters (e.g. coder + reasoning) with SLERP — no training:

```bash
pip install mergekit

cat > /tmp/mergekit.yaml <<EOF
models:
  - model: model/base/Qwen3-1.7B
  - model: model/adapters/urai-coder
  - model: model/adapters/urai-reason
merge_method: slerp
base_model: model/base/Qwen3-1.7B
dtype: bfloat16
EOF

mergekit-yaml /tmp/mergekit.yaml --copy-tokenizer \
  --out-path model/merged/urai-17b-slerp

# Then quantize to GGUF and register as usual
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Distill produces 0 rows | Teacher not responding — check `TEACHER_BASE_URL` and that `urai api` is running |
| Verifier rejects everything | Tasks may be too open-ended; add `--exec` only for code tasks |
| Kaggle notebook OOM | Switch from 4B to 0.6B base, or reduce `per_device_train_batch_size` to 1 |
| Bench score lower than current | Training data quality issue — grow more verified rows before retrying |
| GGUF not found after `urai model add` | Check the path; the file must be in `model/base/` and readable by the `urai` user |
