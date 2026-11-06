# Laya — internal training checkpoint (not a public model)

> **Doc status:** updated 2026-10-29 to match `jev/brand.py` reality.
> Previous version incorrectly listed `laya` as a public model surface.

## What Laya is

Laya is the internal name for the Urai-owned student checkpoint produced by the
distillation pipeline. It is listed as an **internal backend id** inside
`jev/brand.py` — it maps to the `urai` public brand, never appears in
`/v1/models`, and is never selectable by end users.

```python
# jev/brand.py  (excerpt — source of truth)
BRANDS = {
    "urai": {
        "internal": [
            ..., "laya", ...   # folded into the 'urai' public brand
        ]
    }
}
```

The **public surface is exactly two models**: `urai` and `cyberurai`.
Laya weights, when they exist, power the `urai` brand transparently.

## Upgrade path (when training gate passes)

The pipeline produces Laya in three steps:

1. **imatrix quantisation**: domain-matched importance matrix from
   `data/verified/distill-now.jsonl` → `model/base/laya-Q4_K_M.gguf`.
   Same size as Qwen3-4B Q4_K_M, lower perplexity on the task distribution.

2. **LoRA fine-tune** *(gated at ≥ 500 verified rows; current count: 245)*:
   Unsloth QLoRA rank 16 on the verified set (Kaggle T4 path — see
   [KAGGLE_NOW.md](KAGGLE_NOW.md)) → `adapters/<tag>/`.

3. **Laya GGUF** *(gated on bench no-regression)*: LoRA merged + imatrix
   re-quantised → `model/base/laya-Q4_K_M.gguf`. Registered as the `laya`
   entry in `model/registry.json`. Bench gate mandatory: knowledge, math,
   code AND harness benchmarks must not regress — else DISCARD.

## Cutover

```bash
# once the file lands and bench gate passes:
urai model use laya          # restarts llama-server on the new weights
# /v1/models still shows only ["urai", "cyberurai"] — no external change
```

No code change is required. The file drop is the only action.

## Gate status

| Step | Status |
|---|---|
| imatrix quant | pending (needs llama-imatrix run on VPS / CI) |
| LoRA fine-tune | **blocked** — 245/500 verified rows (need 255 more) |
| bench gate | not started |

Run the distill pipeline to grow the verified set:

```bash
# generate + teach + verify + filter
python3 scripts/distill/run_distill.py --categories code,debug,api --n 50
# then re-check: wc -l data/verified/distill-now.jsonl
```
