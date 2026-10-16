# Laya — the Urai-owned student

Laya is Urai's own model brand: same API, Urai-owned weights, no vendor
names anywhere in the product surface. It lands in three upgrades:

1. **imatrix** (in progress): domain-matched importance matrix from
   `data/verified/distill-now.jsonl` → `Qwen3-4B-Q4_K_M-urai.gguf`.
   Same size, lower perplexity, measured on a held-out slice.
2. **LoRA** (gated): Unsloth QLoRA on the verified set (Kaggle T4 ready,
   244 trainer-usable rows) → `adapters/<tag>` → merged.
3. **Laya GGUF**: LoRA-merged + imatrix-quantized export registered as
   `laya` in `model/registry.json`. Bench gate mandatory: knowledge, math,
   code AND harness benchmarks must not regress, else DISCARD.

## Wiring (already live, weights pending)
- `jev/brand.py`: `laya` brand id, ultra tier, student flag.
- Registry `laya` entry points at `model/base/laya-Q4_K_M.gguf`
  (absent = coming soon; `/v1/models` reports availability honestly).
- Tiers route `laya` requests to the strongest local path until the file
  lands; cutover is a file drop + `urai model use laya`, no code change.

## Brand rule
Public surface: `urai`, `urai-fast`, `urai-ultra`, `urai-cyber`, `laya`.
Teacher/backend names (`qwen3-4b`, `llama-local`, `local-student`) appear
only in traces and `urai_metadata`, never as primary model ids.
