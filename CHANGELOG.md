# Changelog

All notable changes to Urai. Format follows [Keep a Changelog](https://keepachangelog.com/),
versioning follows [SemVer](https://semver.org/).

## [3.0.0] — 2026-10-27

### Added
- **Urai Studio** (`/app`): chat, vibe code, wiki, agents, API keys and settings in one UI.
  Premium off-white theme, 3D pill cards, motion, streaming answers.
- **API keys from the web**: generate → copy → revoke, with unlimited quota option
  (`GET/POST/DELETE /v1/keys*`).
- **Desktop app** (`desktop/`): Electron shell for Windows (NSIS + portable) and
  Linux (AppImage + .deb). Starts the API, opens the Studio, graceful shutdown.
- **PWA**: manifest, service worker, maskable icons, install prompt, panel deep links.
- **CLI**: `studio`, `tui`, `key`, `vibe`, `wiki`, `agents`, `routines`.
- **`.env` loading**: `urai api`/`studio`/desktop read `.env` (cwd, then repo
  root) without overriding exported variables.
- **Read-only API**: `GET /v1/wiki/search`, `/v1/wiki/list`, `/v1/wiki/get`,
  `/v1/agents/list`, `/v1/routines/list`.
- **`POST /vibe`**: server-side vibe coding session (master key only).
- **`DELETE /v1/keys/<id>`**, `/v1/agents/<id>`, `/v1/routines/<id>`.
- **Studio wiki panel**: browse and add pages (3-tier memory, BM25 search,
  `[[wikilinks]]`) over the new read-only routes.
- **Studio agents panel**: create, inspect and talk to named persistent agents
  (schedules, private notes, history).
- **Studio routines**: scheduled recurring tasks wired to the due-run scheduler.
- IterResearch deep research, evidence ledger, chart generation, appshots,
  ACP voice protocol, vector RAG memory, tool guard hooks.
- 18 skills including ports of Anthropic's `webapp-testing`, `mcp-builder`,
  `skill-creator`, `canvas-design`, `frontend-design`.
- GitHub Pages live demo: <https://etside.github.io/urai/>

### Changed
- Per-IP sliding-window rate limiting (`URAI_RATE_LIMIT`, `URAI_RATE_WINDOW`).
- Request timeouts (`URAI_REQUEST_TIMEOUT`) and structured file logging (`URAI_LOG_FILE`).
- `URAI_MASTER_KEY` comes from the environment; the unset fallback is
  loudly labelled and warns at startup.
- Static shell assets are served by the API server (manifest, SW, icons).
- CI: both workflows run v3 checks and import every module.

### Fixed
- `GET /v1/keys` raised `NameError` (`is_master` undefined in `do_GET`).
- `GET /v1/rate-limit-status` raised `UnboundLocalError` (`ip` used before assignment).
- `DELETE /v1/keys/<id>` returned 501 (no `do_DELETE`).
- Studio called GET for routes that were POST-only (wiki, agents, routines).
- Studio vibe panel posted to a non-existent `/vibe` route.
- Studio defaulted its API URL to the Pages origin; now falls back to
  `http://127.0.0.1:8777` on `*.github.io` and `file://`.
- Service worker was registered from a `data:` URL (rejected by browsers).

### Removed
- Hardcoded `856777` master key and retired `urai.daddyai.online`
  references from docs, defaults, installers and CI.

## [2.x]

Earlier history: local Qwen3 inference, OpenAI-compatible API, voice, vision,
image generation, embeddings, distill/eval pipeline, swarm, plugins, MCP.

[3.0.0]: https://github.com/etside/urai/compare/v2.0.0...v3.0.0
