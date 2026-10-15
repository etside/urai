# Urai Stage-2 GPU Plan — One Hour, H100, Unsloth First

This is the controlled path. Do NOT run long GPU jobs on the 8GB CPU droplet.

## Selected profile (fastest practical, cost-capped)
- DigitalOcean ephemeral GPU droplet:
  - size: `gpu-h100x1-80gb`
  - region: `tor1`
  - image: `gpu-h100x1-base`
  - max runtime: 1 hour
- Dataset gate: `data/verified/distill-now.jsonl >= 500` rows
- Base: `unsloth/Qwen3-4B-bnb-4bit`
- Training method: Unsloth QLoRA, rank 16, batch 2, grad acc 4,
  LR 2e-4, `adamw_8bit`, Unsloth gradient checkpointing, seq-len 2048
- Smoke/controlled run: 300 max steps (usually completes under 1 hour)
- Output:
  - `adapters/distill-now-gpu`
  - adapter uploaded to GitHub release asset
  - droplet destroyed automatically after cap
- Nightly/tracked proof before promotion:
  - `model (fast) bench` or Urai evaluation must not regress knowledge/math/code
  - reject the adapter if it leaks instructions or copies raw task phrasing

## Repo capability map for training and inference
- `unslothai/unsloth` + `bitsandbytes`: first training stack for QLoRA
- NVIDIA `Model-Optimizer`: post-training quantization/distillation export path
- `vllm-project/llm-compressor`: optional later production inference/export
- NVIDIA DALI: only if raw input pipeline becomes bottleneck
- `llmfit`: optional sizing helper before run
- NVlabs/LongLive: reference for long multimodal/video-world-model style generation
- MaxLiu22/Motion2MixamoRig: reference for video-to-character motion capture and `.glb` export
- Creatorberry/flick: reference for scene-by-scene animation generation from scripts/video
- Ox Alpha ecosystem: benchmark/forensics reference used by independent reproducibility work

## Safety rules
- API token is only read from environment / GitHub secrets:
  - `DO_API_TOKEN`
  - Urai repo token for push/upload can reuse `gh auth`
- Never put the token in git, images, logs, or command history
- Always dry-run the script first; only pass `create`
- The orchestrator deletes the droplet even if training fails

## Urai project audit notes
- Current git tree is clean except expected generated `train-now` rows/report
- No embedded DigitalOcean token or live private key in source tree
- The only `password = 'hunter2'` marker is harmless fixture/example data
- Existing runtime is green and local model gated by pin
- Watch for broad vulnerability surfaces in:
  - `/tools` JSON execution on the VPS
  - large 13GB model tree on an 8GB runtime
  - long CPU distillation jobs
- Current short-term optimization wins:
  - context length reduction from 4096 to 2048 during generation-heavy runs
  - CPU threads locked to `4`
  - KV-cache/prefetch caution under 8GB memory
  - GPU training adapters merged offline, not in runtime<|constrain|>