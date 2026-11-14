---
name: open-manus
description: "Multi-agent orchestration patterns from OpenManus. Use for complex tasks requiring planning, tool use, browser control, code execution, and parallel agent coordination. Covers PLAN→EXECUTE→VERIFY loop, MCP tool integration, chart visualization, and RL-tuned agent workflows."
source: https://github.com/FoundationAgents/OpenManus
---

# OpenManus Patterns (Urai)

Urai's agent system is based on OpenManus patterns: PLAN→TOOL→VERIFY loop with parallel sub-agents.

## Core Agent Loop

```
1. PLAN: Break task into steps, identify tools needed
2. EXECUTE: Run tools (browser, code, search, write)
3. VERIFY: Check result, retry if needed
4. DONE: Return structured result
```

## Available Tools in Urai

| Tool | Description |
|------|-------------|
| `web_search` | Search the web |
| `web_fetch` | Fetch a URL |
| `browser_run` | Control a browser |
| `code_run` | Execute Python/bash |
| `write_file` | Write a file |
| `read_file` | Read a file |
| `wiki_search` | Search Urai knowledge base |
| `wiki_add` | Add to knowledge base |
| `imagine` | Generate an image |
| `video_gen` | Generate a video |
| `voice_speak` | Text-to-speech |
| `vision_see` | Analyze an image |

## Multi-Agent Patterns (from OpenManus)

### Swarm (parallel)
```json
{
  "tool": "swarm",
  "args": {
    "tasks": [
      "Research competitor A pricing",
      "Research competitor B pricing",
      "Research competitor C pricing"
    ],
    "merge": "summarize"
  }
}
```

### Conductor (sequential planning)
```json
{
  "tool": "conductor",
  "args": {
    "goal": "Write a research report on quantum computing",
    "max_agents": 3
  }
}
```

## Chart Visualization (OpenManus)

Urai supports VChart-powered chart generation:
```bash
urai agent "create a bar chart showing monthly revenue: Jan 10k, Feb 15k, Mar 12k"
```

Returns SVG/PNG chart via the chart tool.

## RL-Tuned Agent (OpenManus-RL)

Urai's self-training pipeline includes RL tuning for the agent loop:
- Trajectory generation and scoring
- Reward from task completion
- Weekly distillation cycle

## MCP Integration

```bash
# Run Urai as MCP server
urai serve mcp --port 8778

# Connect OpenManus to Urai MCP
python run_mcp.py --server http://localhost:8778
```
