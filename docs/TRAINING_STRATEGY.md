# Urai v1.04 — Training Strategy

## Why g4dn.xlarge (T4 GPU) is Optimal for Urai v1.04

Urai v1.04 is a **0.6B parameter** model fine-tuned from `urai-qwen3-06b` with LoRA (r=16).
At this scale, a single NVIDIA T4 (16 GB VRAM) is the sweet spot: it has more than enough VRAM
for 4-bit QLoRA fine-tuning of a 0.6B model, and spot pricing on `g4dn.xlarge` in `ap-south-1`
sits around **$0.25/hr** — the most cost-efficient GPU option available on AWS.

---

## Training Optimizations Applied

| Optimization | Status | Notes |
|---|---|---|
| **4-bit QLoRA** (bitsandbytes) | ✅ enabled | Reduces VRAM from ~2.4 GB (fp32) to ~0.6 GB for 0.6B params; frees headroom for activations and optimizer states |
| **Flash Attention 2** | ✅ enabled | Fused attention kernel; reduces peak VRAM and speeds up forward/backward pass |
| **Gradient Checkpointing** | ✅ enabled | Trades compute for memory: recomputes activations on backward pass instead of storing them |
| **Sequence Packing** | ✅ enabled | Packs short sequences into full context windows to eliminate wasted padding and improve GPU utilization |
| **fp16 Mixed Precision** | ✅ fp16 | **T4 does NOT support bf16**. The config sets `dtype: fp16`. On A100/A10G, override to bf16 for better numeric stability |
| **DeepSpeed ZeRO-1** | conditional | Only if multi-GPU. Single g4dn.xlarge is single-GPU; not needed here but available for scale-out |
| **Dataloader Workers** | 4 | Overlaps CPU data loading with GPU compute |
| **Pin Memory** | ✅ enabled | Speeds host→device transfers |

---

## Expected Training Time

Model: Urai-0.6B (qwen3-06b base) | LoRA r=16 | 3 epochs | ~10,000 training samples

| Phase | Estimated Duration |
|---|---|
| Instance boot + setup | ~5–8 min |
| pip install (flash-attn, bitsandbytes) | ~3–5 min |
| Data preparation | ~1–2 min |
| **Training (3 epochs, ~10k samples)** | **~45–90 min** |
| GGUF export + quantisation | ~3–5 min |
| S3 upload | ~1 min |
| **Total wall time** | **~60–110 min** |

> Note: At 0.6B params with QLoRA r=16 on a T4, throughput is roughly 1,000–2,000 tokens/sec.
> 10k samples × 512 avg tokens × 3 epochs = ~15M tokens → ~45–90 min.
> Larger datasets or longer sequences will scale linearly.

---

## Cost Estimate

| Resource | Rate | Duration | Cost |
|---|---|---|---|
| g4dn.xlarge spot (ap-south-1b) | ~$0.25/hr | ~1.5 hr | **~$0.37** |
| S3 storage (<1 GB GGUF) | ~$0.023/GB/mo | negligible | **<$0.01** |
| **Total estimated cost** | | | **~$0.20–0.40** |

---

## Why This Beats Alternatives

- **p3.2xlarge (V100, 16 GB)**: ~$0.90/hr spot → 3× more expensive, V100 doesn't support Flash Attention 2, no practical throughput gain for 0.6B.
- **Local CPU (no GPU)**: 50–100× slower; training that takes 1 hour on T4 takes 2–4 days on CPU. Not practical.
- **g5.xlarge (A10G, 24 GB)**: $0.34/hr spot — good upgrade path if VRAM OOM occurs, supports bf16 and slightly faster matrix math, but overkill for 0.6B with QLoRA.
- **p4d.24xlarge (A100×8)**: ~$10/hr — reserved for models >7B or very large batch experiments.

---

## Hardware Comparison Table

| Instance | GPU | VRAM | Spot Price | FA2 | bf16 | Recommended For |
|---|---|---|---|---|---|---|
| **g4dn.xlarge** ✅ | T4 | 16 GB | ~$0.25/hr | ✅ | ❌ (use fp16) | Urai v1.04 (0.6B), cost-optimised |
| g5.xlarge | A10G | 24 GB | ~$0.34/hr | ✅ | ✅ | Upgrade if VRAM OOM; 1B–3B models |
| p3.2xlarge | V100 | 16 GB | ~$0.90/hr | ❌ | ❌ | Legacy; 3× cost, no advantage here |
| p4d.24xlarge | A100×8 | 320 GB | ~$10/hr | ✅ | ✅ | 7B+ models, multi-GPU experiments |
| CPU only | — | — | ~$0.05/hr | ❌ | ❌ | Development / smoke tests only |

---

## When to Upgrade to g5.xlarge

Upgrade from g4dn.xlarge to g5.xlarge (A10G, 24 GB VRAM) if:

1. **CUDA OOM** errors appear during training, even with QLoRA + gradient checkpointing.
2. You increase LoRA rank beyond r=32 or sequence length beyond 8192.
3. You switch from QLoRA to full LoRA (without 4-bit quantisation).
4. You scale to a 1B+ base model.

To upgrade, change `instance_type: g4dn.xlarge` → `g5.xlarge` and `max_spot_price: "0.50"` → `"0.60"`
in `configs/distill_qwen3_4b.yaml`, then re-run `bash scripts/launch-training-aws.sh`.

---

## bf16 vs fp16 — T4 Gotcha

The NVIDIA T4 GPU does **not** support bfloat16 (bf16) in hardware. Attempting to train with
`--bf16` on a T4 silently falls back to fp32 in some frameworks, causing memory bloat and
incorrect loss scaling. The training scripts and config in this repo **explicitly set fp16 for T4**.

On A100 and A10G, bf16 is preferred: it has the same memory footprint as fp16 but better numeric
range (8-bit exponent vs 5-bit), reducing the risk of loss divergence.

The `train-optimized.py` script auto-detects GPU type and sets the correct dtype automatically.

---

## Quick Start

```bash
# Launch training on AWS (requires ~/.ssh/urai-deploy.pem and aws CLI authenticated)
bash scripts/launch-training-aws.sh

# Or run locally (auto-detects hardware)
python scripts/train-optimized.py

# Dry run (print command without executing)
python scripts/train-optimized.py --dry-run
```
