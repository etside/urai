# Muse Spark Open in Urai

Hosted teacher/consult via OpenRouter — **not** a local download.

**Why not self-host?** Muse Spark Open is 816B MoE (42B active/token, 1M ctx).
Weights: BF16 ~1.6 TB, NVFP4 ~530 GB, smallest GGUF ~300 GB. Urai runs on
3 GB laptops, `t3.small` VPS, and Kaggle T4s — impossible. So Urai calls it
through OpenRouter (Fireworks / Makora / Modal / Together / Nebius / Baseten).

Ref: [Build with Muse Spark Open](https://dev.meta.ai/resources/blog/build-with-muse-spark-open)
Model: [meta/muse-spark-open](https://openrouter.ai/meta/muse-spark-open)

## What you get

| Capability | How |
|---|---|
| Text chat (1M ctx) | `POST /v1/chat/completions` → OpenRouter |
| Image / video / audio | `content: [{type:image_url,…},{type:video_url,…},{type:input_audio,…}]` pass-through |
| PDF | Upload PDF → Urai extracts text → chunked into 1M window as context |
| Reasoning | `reasoning_effort: low/medium/high/xhigh` (per request or `URAI_REASONING_EFFORT`) |
| Tool calling | `tools: [{type:function,…}]` + `tool_calls` back (parallel calls supported) |
| Streaming | `stream: true` — required for long reasoning |

## Setup

```bash
export OPENROUTER_API_KEY=sk-or-...   # https://openrouter.ai/settings/keys
export URAI_CLOUD_CONSULT=1 URAI_CLOUD_1M=1
export URAI_REASONING_EFFORT=high     # low|medium|high|xhigh
urai api --port 8777
```

Or put the keys in `.env` (see `.env.example`):
```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=meta/muse-spark-open
URAI_CLOUD_CONSULT=1
URAI_CLOUD_1M=1
```

## API usage

```bash
curl https://urai.example.com/v1/chat/completions \
  -H "Authorization: Bearer $URAI_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "urai",
    "messages": [
      {"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "https://example.com/chart.png"}},
        {"type": "text", "text": "What does this chart say?"}
      ]}
    ],
    "reasoning_effort": "high",
    "stream": true
  }'
```

Urai keeps its identity: Muse Spark is a **tool** (marked `[cloud-consult:muse-spark-open]`).
The local Qwen3 student writes the final answer; Muse Spark supplies research,
multimodal understanding, and verification.

## Distill (Kaggle)

```bash
# 1. Generate teacher data (your machine, needs OpenRouter key)
python3 kaggle/teacher_muse_spark.py \
  --tasks data/raw_tasks/sample_tasks.jsonl \
  --out data/finetune/muse-spark-open/train.jsonl --limit 500

# 2. QLoRA on Kaggle (uses existing kaggle/train_qlora.py)
kaggle kernels push -p etside/urai-muse-distill -f kaggle/train_qlora.py
```

Config: `configs/distill_muse_spark_open.yaml`
Output: `urai-v-next.gguf` → `urai model use urai-v-next`

## Pricing (OpenRouter, pay-as-you-go)

- $1.25 / M input tokens, $4.25 / M output tokens (all providers equal)
- 401 invalid key · 402 no credits · 429 rate-limit (retry with backoff)
- **Free until public release** per owner decision — no billing gate, only
  `URAI_RATE_LIMIT` (default 120/min public) + `URAI_MASTER_KEY`.

## Public deploy (both hosts)

```bash
export URAI_DOMAIN=urai.example.com
bash deploy/deploy-public.sh --both   # Tailscale VPS + AWS EC2
```

- AWS SG: allow `80`, `443` from `0.0.0.0/0` (Caddy terminates TLS).
- Tailscale VPS: reachable via `tailscale ssh wearimpressive-vps`.
- `.env` on host: `URAI_PUBLIC=1`, `URAI_FREE_MODE=1`, master key set, CORS = your domain.
