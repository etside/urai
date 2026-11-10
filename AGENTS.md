# Urai — Agent Instructions

## Repository layout
- jev/ — core Python runtime (54 modules)
- jev/server.py — HTTP API server (OpenAI-compatible)
- jev/agent.py — agent loop (PLAN→TOOL→VERIFY)
- jev/cli.py — CLI entry point
- jev/rag.py — document RAG engine
- model/ — model registry and weights
- skills/ — agent skill packs
- scripts/ — training and distillation

## Running Urai

```bash
urai api --port 8777        # start API
urai ask "hello"            # one-shot
urai chat                   # interactive
urai tui                    # terminal UI
```

Live API: http://52.66.18.45:8777

## Key conventions
- All API routes in jev/server.py do_GET/do_POST
- New tools registered in jev/tools.py TOOLS dict + TOOL_SCHEMAS list
- New skills: create skills/<name>/SKILL.md with frontmatter
- Batch commits via scripts/gh_batch_commit.sh
- No local builds — use GitHub Actions or AWS EC2
