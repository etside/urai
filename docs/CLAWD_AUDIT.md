# Clawd-Code / Not-Clawd-Code Feature Audit for Urai

Audit comparing features in **clawd-code** ([GPT-AGI/Clawd-Code](https://github.com/GPT-AGI/Clawd-Code) — Python rebuild of Claude Code) and **not-clawd-code** ([uzuma645/not-clawd-code](https://github.com/uzuma645/not-clawd-code) — Bun/TS rebuild) against Urai's current capabilities.

For each feature: what it is, whether Urai already has it, and whether to pick it up.

---

## Features found in clawd-code (GPT-AGI/Clawd-Code)

### 1. Tool System with Registry + Protocol

`src/tool_system/` defines `ToolSpec`, `ToolRegistry`, `ToolContext`, `ToolResult`, `ToolPermissionContext`. Registered tools: `bash`, `read`, `write`, `edit`, `glob`, `grep`, `web_fetch`, `web_search`, `mcp`, `lsp`, `todo_write`, `plan_mode`, `skill`, `sleep`, `worktree`, `agent`, `brief`, `team`.

- **Urai has:** `jev/tools.py`, `jev/cli.py` with bash/file ops. No formal tool registry or protocol.
- **PICKUP:** Tool registry pattern for extensible tools. Not all tools — just the registry/protocol interface so Urai can add tools modularly.

### 2. Context System

`src/context_system/` builds the context prompt from a workspace snapshot, git context, and `CLAUDE.md` instructions. `builder.py` assembles runtime context.

- **Urai has:** `jev/context.py` (basic).
- **PICKUP:** Git context injection (branch, recent commit, status) into prompts. Workspace snapshot (file counts, key files).

### 3. Compact Service

`src/compact_service/` performs conversation compaction with **microcompact** (strip images), LLM-generated summary, and boundary markers. 4096 token summary budget.

- **Urai has:** nothing — conversations grow unbounded.
- **PICKUP:** Microcompact + summary-based compaction. Critical for long sessions on low-RAM VPS.

### 4. Skills System

`src/skills/` loads `.md` skill files from `~/.clawd/skills` or env dirs. Frontmatter parsing, argument substitution.

- **Urai has:** `skills/` dir with `SKILL.md` files but no loader.
- **PICKUP:** Skill loader with env-based directory resolution and frontmatter parsing.

### 5. Bash Safety Patterns

Dangerous command regex patterns (`sudo`, `shutdown`, `mkfs`, `dd`, `rm -rf /`, fork bomb). Truncation at 20k chars.

- **Urai has:** `jev/tools.py` has basic bash but no dangerous command protection.
- **PICKUP:** Dangerous command pattern list + refusal.

### 6. Permission System

`ToolPermissionContext` with `deny_names`, `deny_prefixes`, `workspace_root`, `additional_working_directories`, `allow_docs`. Path resolution + containment checks.

- **Urai has:** nothing.
- **PICKUP:** Path containment + deny-list for tool execution safety.

### 7. Provider Abstraction

`BaseProvider`, `AnthropicProvider`, `MinimaxProvider`. Multi-provider support.

- **Urai has:** `jev/backends.py` (`LlamaServerBackend`, `TeacherAPIBackend`, `GeminiBackend`, `DeepSeekBackend`, `QwenBackend`, `NemotronBackend`, `VideoGenBackend`, `MockBackend`).
- **ALREADY HAVE:** Urai's backend system is more comprehensive. No pickup needed.

### 8. Agent Loop

`src/tool_system/agent_loop.py` — multi-turn tool calling with conversation state and tool result summarization.

- **Urai has:** `jev/agent.py` (plan/tool/verify loop).
- **PARTIAL:** Urai has an agent loop but lacks tool result summarization (keeping context compact).
- **PICKUP:** Tool result summary format.

---

## Features found in not-clawd-code (uzuma645/not-clawd-code)

### 1. Tool Pool / Coordinator Mode

`src/utils/toolPool.ts` merges built-in + MCP tools, deduplicates, and supports coordinator mode filtering for restricted tool sets.

- **Urai has:** `jev/tools.py` with a fixed tool set.
- **PICKUP:** Tool pool deduplication + coordinator mode (restricted tool set for sub-agents).

### 2. Token Budget Parsing

`src/utils/tokenBudget.ts` parses user intent like "+500k tokens" or "use 2M tokens" from natural language.

- **Urai has:** `model/budget.json` (disk/RAM budget, not token budget).
- **PICKUP:** Token budget from natural language user input.

### 3. Tool Search / Deferred Loading

`src/utils/toolSearch.ts` dynamically discovers deferred tools when MCP tool descriptions exceed 10% of the context window.

- **Urai has:** nothing.
- **PICKUP:** Deferred tool loading for MCP tools to save context tokens.

### 4. Microcompact

Strip images before compaction, referenced in `compact_service`.

- Same as clawd-code's compact. Already noted above.

### 5. Bridge System

`src/bridge/` for remote execution (bridge API, config, messaging, pointer, status).

- **Urai has:** nothing.
- **SKIP:** Bridge is for desktop app integration. Urai is CLI/server only. Not needed.

### 6. Vim Mode

`src/vim/` with motions, operators, text objects, transitions.

- **Urai has:** nothing.
- **SKIP:** Vim mode is a TUI feature. Urai is CLI + API server. Not applicable.

### 7. Voice Mode

`src/voice/`.

- **SKIP:** Not applicable to Urai's use case.

### 8. Telemetry

`src/utils/telemetry/` event logging.

- **Urai has:** `/tmp/urai-routing.jsonl` (routing log).
- **PARTIAL:** Already have routing log. SKIP additional telemetry.

### 9. Worktree Support

`src/utils/worktree.ts` for git worktree operations.

- **Urai has:** nothing.
- **PICKUP:** Git worktree for parallel agent execution.

### 10. Transcript Search

`src/utils/transcriptSearch.ts` searching conversation history.

- **Urai has:** nothing.
- **PICKUP:** Transcript search for long conversations.

---

## Summary

| Feature | clawd-code | not-clawd-code | Urai current | Action |
|---------|:----------:|:--------------:|:-----------:|--------|
| Tool Registry | ✅ | ✅ | ❌ | PICKUP: registry pattern |
| Context Builder | ✅ | ❌ | basic | PICKUP: git/workspace context |
| Compact Service | ✅ | ✅ | ❌ | PICKUP: microcompact + summary |
| Skills Loader | ✅ | ❌ | files only | PICKUP: loader with frontmatter |
| Bash Safety | ✅ | ❌ | ❌ | PICKUP: dangerous command patterns |
| Permissions | ✅ | ❌ | ❌ | PICKUP: path containment + deny-list |
| Multi-Provider | ✅ | ✅ | ✅ (better) | ALREADY HAVE |
| Agent Loop | ✅ | ✅ | partial | PICKUP: tool result summaries |
| Tool Pool | ❌ | ✅ | ❌ | PICKUP: dedup + coordinator mode |
| Token Budget | ❌ | ✅ | ❌ | PICKUP: natural language parsing |
| Deferred Tools | ❌ | ✅ | ❌ | PICKUP: save context tokens |
| Bridge | ❌ | ✅ | N/A | SKIP |
| Vim Mode | ❌ | ✅ | N/A | SKIP |
| Voice | ❌ | ✅ | N/A | SKIP |
| Worktree | ❌ | ✅ | ❌ | PICKUP: parallel agents |
| Transcript Search | ❌ | ✅ | ❌ | PICKUP: conversation history |

---

## What NOT to pick up (cons/excluded)

- **No crons or scheduled tasks** — both repos have cron tools; Urai excludes crons.
- **No TUI/ink/render system** — Urai is CLI + API server, not a terminal UI.
- **No desktop bridge/remote execution** — Urai runs on VPS, no desktop needed.
- **No voice/vim** — out of scope for a local LLM runtime.
- **No telemetry/analytics** — privacy-first; routing log is enough.
- **No team/collaboration features** — Urai is single-user.
- **No plan_mode** — Urai's router already handles complexity routing.
