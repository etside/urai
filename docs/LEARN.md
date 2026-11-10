# Urai learning loop — how the model learns from the whole internet

Three gears, cheapest first. Everything lands as distill-ready tasks.

## Gear 1 — Urai browses itself (keyless, everywhere, on now)

The agent grew `web_search` + `web_fetch` (no API keys):

- **search**: Wikipedia + HackerNews + GitHub repos + arXiv, one call
- **fetch**: any public http(s) page → cleaned text (300 KB cap,
  private hosts blocked = SSRF-safe)
- Agent use: emit a ```` ```tool ```` block, same as read_file/run/see —
  see `jev/agent.py` SYSTEM prompt. Also callable via API `/tools` and CLI.

```bash
./bin/urai agent "research Qwen3 LoRA best practices and summarize"
```

## Gear 2 — ingest research into training fuel

```bash
# URLs from anywhere (agent runs, OpenClaw, hand-picked):
python3 scripts/learn/ingest.py --topic qwen3-lora \
    --urls urls.txt --out data/raw_tasks/learned/qwen3-lora.jsonl
# then distill + train as usual:
python3 scripts/distill/run_distill.py --tasks data/raw_tasks/learned/qwen3-lora.jsonl \
    --out data/verified/learn-qwen3-lora.jsonl
```

Dedupes by content hash across all previous ingests. JS-heavy pages:
`scripts/learn/render.py` (needs Playwright — preinstalled on the VPS).

## Gear 3 — OpenClaw research runs (the tireless intern)

OpenClaw (tool-capable agent, own workspace/memory/browser skill) does
multi-hour research while Urai trains/serves:

```bash
# on the machine running openclaw:
openclaw agents run "Research <topic>. Write raw findings as markdown files
  to <urai>/research/<topic>/ (one file per source, URL header on top).
  No summaries without quotes. Cover docs, papers, repos, HN threads."
python3 scripts/learn/ingest.py --topic <topic> \
    --urls <(ls research/<topic>/*.md) ...
```

(ingest takes URLs; for local .md files, convert each to `file://` lines
or paste contents — v2 will accept directories directly.)

## Gear 4 — headless browser (VPS, JS pages)

Installed on the droplet (root apt): `playwright + chromium-headless`.
Smoke-tested against example.com. Use for pages Gear 1 can't read:

```bash
ssh root@<droplet> 'cd /opt/urai && python3 scripts/learn/render.py \
    --urls /tmp/urls.txt --out /tmp/rendered.jsonl'
```

## What NOT to do

- Don't crawl aggressively: default politeness (one URL at a time, 25s
  timeouts). Respect robots.txt for big crawls (v2).
- Don't ingest secrets: ingest skips nothing — curate `urls.txt`.
- Don't train on raw web text directly: always through
  ingest → distill (verify/filter) → train. Garbage in, garbage out.
