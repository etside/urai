# Urai training guide — faster + better, latest open methods (Oct 2026)

## The setup (read this first)

This box (2-core m3, 3.3 GB RAM, no GPU) **orchestrates**; free cloud GPUs
**train**. Each side does what it's good at:

| Where | Free budget | Job |
|---|---|---|
| This box | 24/7 | distill data → verify → serve → eval → release |
| Kaggle notebooks | 30 GPU-hrs/wk, T4×2, 12h sessions | **primary trainer** (Unsloth QLoRA) |
| Google Colab | T4, ~4–12h, unpredictable | backup trainer / quick tests |
| GitHub Actions | 2000 CPU-min/mo | builds, CI, release bundles |
| HuggingFace Hub | unlimited public | home for adapters, GGUFs, datasets |

## The weekly loop (end to end, $0)

1. **Grow data here** (this box, offline, free):
   `generate_tasks.py --seed <new>` → `run_distill.py --system reasoning
   --exec --judge` → `data/verified/distill-vX.jsonl`. Aim: hundreds→
   thousands of kept records before each training run (41 is a start, not
   a training set).
2. **Pack**: `python3 scripts/train/pack_dataset.py --inputs
   data/verified/distill-vX.jsonl --out /tmp/urai-train-data.tar.gz` →
   upload once as a Kaggle Dataset (survives the no-internet GPU rule).
3. **Train** (Kaggle, T4×2, Internet ON): open
   `notebooks/train_urai_qlora.ipynb`, train Qwen3-0.6B (~15 min) or
   1.7B, push adapter to `tukitattu/urai-*` on HF Hub.
4. **Bring it home**: download adapter → merge + GGUF export →
   `model/base/` → `urai model bench` → registry → `urai serve` →
   eval vs previous best in `eval/reports/`.
5. **Ship**: commit, tag `vX.Y`, Actions builds the full bundle + Release.

Urai's CPU box **cannot train weights** (no GPU, 3 GB RAM). The proven split:

1. **Distill here** (this repo, offline): teacher → verifier → filter →
   `data/verified/*.jsonl` — done, deterministic, free.
2. **Train on a GPU elsewhere** (free Colab T4 works for ≤8B): Unsloth QLoRA
   on the verified set → LoRA adapter (MBs, not GBs).
3. **Bring it home**: merge adapter → quantize GGUF → `urai model bench` →
   register → serve. Same runner, same API, better brain.

## Method 1 — Unsloth QLoRA (recommended, 2x faster, 70% less VRAM)

Ref: https://github.com/unslothai/unsloth · https://docs.unsloth.ai

```bash
# Colab (free T4) or any NVIDIA Linux box, Python 3.10/11:
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git" \
    trl peft accelerate bitsandbytes datasets
python3 scripts/train/sft_unsloth.py \
    --model unsloth/Qwen3-0.6B-bnb-4bit \
    --train data/verified/distill-v0.2.jsonl \
    --out model/adapters/urai-qwen3-06b-v1
```

Canonical recipe (baked into the script): 4-bit base, `r=16`/`alpha=16`,
all linear layers (`q/k/v/o + gate/up/down`), `lr=2e-4`, 1–3 epochs,
`use_gradient_checkpointing="unsloth"`. 0.5–1.7B trains in minutes on a T4;
7–8B fits 16 GB VRAM. Then merge + export GGUF (commands printed by the
script) and copy the `.gguf` into `model/base/`.

## Method 2 — Reasoning distillation (R1-style think traces)

Small models gain the most from learning **traces**, not just answers
(see DeepSeek-R1-Distill-Qwen line). Urai supports it end to end:

```bash
# 1. distill with a thinking teacher (R1-distill / Qwen3 / strong chat):
export TEACHER_BASE_URL=... TEACHER_API_KEY=... TEACHER_MODEL=...
python3 scripts/distill/run_distill.py --tasks data/raw_tasks/expanded \
  --out data/verified/distill-reasoning.jsonl \
  --report eval/reports/distill-reasoning.json \
  --system reasoning --exec --judge
# 2. train on it with Method 1 (traces ride along in the completion text)
```

Mock/offline runs ignore `--system` (deterministic, for pipeline tests).

## Method 3 — Model merging (zero-GPU capability gain)

Ref: https://github.com/arcee-ai/MergeKit

Merge two fine-tunes (e.g. coder adapter + reasoning adapter) with SLERP —
no training, often +accuracy:

```yaml
# mergekit.yaml
models:
  - model: base/Qwen3-1.7B
  - model: adapters/urai-coder
  - model: adapters/urai-reason
merge_method: slerp
base_model: base/Qwen3-1.7B
dtype: bfloat16
```

```bash
pip install mergekit && mergekit-yaml mergekit.yaml --copy-tokenizer \
  --out-path model/merged/urai-17b-slerp
# then llama.cpp: llama-quantize -> Q4_K_M.gguf -> registry
```

## Speed (inference) — what actually works, verified on our stack

Runner: llama.cpp `llama-server` b11559 (locally verified flags).

| Method | How in Urai | Expected gain | Needs |
|---|---|---|---|
| KV-cache quant | default on: `-ctk q8_0 -ctv q8_0` | less RAM, often faster | nothing |
| Flash Attention | auto default (verified flag exists) | faster prefill | nothing |
| ngram speculative | `urai serve start --spec ngram-mod` | 1.2–1.6x decode, free | nothing |
| IQ quants | `IQ4_XS` GGUFs | smaller + faster than Q4_K_M | re-download |
| EAGLE-3 drafts | `--spec-type draft-eagle3 --md <head>` | 1.6–3.3x (paper numbers) | draft head for the model |
| Bigger engine | vLLM/SGLang on a GPU box | 2–10x at concurrency | NVIDIA + rewrite of serve_ctl |
| MoE models | Qwen3-30B-A3B (3.3B active) | ~1.5x vs dense 7B same GPU | 40GB+ VRAM box |

Notes: AWQ is a ~2.5x free lunch **on vLLM/CUDA**, not on llama.cpp/CPU —
stay GGUF here. EAGLE-3 shines on GPU; on this CPU box ngram-spec + KV
quant is the practical combo (bench both with `urai model bench` and keep
the faster in `eval/reports/`).

## Better base models (drop-in, same runner)

| Model | Size | Why | Registry id |
|---|---|---|---|
| Qwen3-0.6B Q8_0 | ~0.7 GB | newer + stronger than 0.5B | `qwen3-06b` ✅ |
| Qwen3-1.7B Q4_K_M | ~1.1 GB | best 1–2B open model | `qwen3-17b` ✅ |
| Qwen3-8B / 14B | 5–9 GB | needs 8GB+ box | add when hosted |
| gpt-oss-20B | ~13 GB | open weights, strong | GPU box only |
| Qwen2.5-VL-3B | ~2.6 GB | vision (already wired) | `qwen25vl-3b` ✅ |

Refs: https://github.com/QwenLM/Qwen3 ·
https://huggingface.co/ggml-org (GGUF builds) ·
https://github.com/vck/unsloth (4-bit prequants) ·
https://github.com/sgl-project/sglang (EAGLE-3/serving) ·
https://github.com/vllm-project/vllm (serving/AWQ) ·
benchmarks: https://github.com/ree2raz/inference-bench

## Bench protocol (nothing invented)

Every claim lands in `eval/reports/` with command + box + commit:

```bash
./bin/urai model bench --id <id>            # llama-bench row
./bin/urai serve start --model <id> [--spec ngram-mod]
python3 scripts/distill/run_distill.py ...  # quality gates
```
