# Urai agent swarm, plugins & human-like browser

## 1. Swarm — multiple tasks at once (Kimi/Hermes-style)

```bash
urai swarm "summarise README" "write retry helper with tests" --workers 2
urai swarm "t1" "t2" "t3" --remote        # fan out on the VPS /agent/swarm
```

API: `POST /agent/swarm {"tasks": ["...", {"task":"...","budget_tokens":4096}],
"max_workers": 3, "device_id": "..."}` (master key = unlimited cost 0,
guests share the 5-free budget). MCP: `urai_swarm`. Each task runs the full
plan/tool/verify loop in its own thread; one failure never blocks the rest.

## 2. Plugins — OpenClaw-style (`urai plugin …`)

```
plugins/<name>/plugin.json   {"name","version","description","enabled","hooks":[]}
```

```bash
urai plugin list
urai plugin enable browser
urai plugin serve telegram     # needs TELEGRAM_BOT_TOKEN (+URAI_REMOTE_URL/URAI_MASTER_KEY)
```

Built-ins: **browser** (hook `browser` → human-like runs), **telegram**
(hook `message` → answers via Urai API). Channel plugins never store chat
history; they forward text and stream the answer back.

## 3. Browser — device browser that clicks like a human

Step DSL (deterministic, logged): `goto(url)` → `click(selector|text)` →
`fill(selector, value)` → `wait` → `snapshot`/`screenshot`. Random
300–1200 ms pauses, rotated viewports/user-agents, hover-before-click,
typed input. Private hosts blocked unless `URAI_BROWSER_ALLOW_PRIVATE=1`.

```bash
urai browse "check order status" --steps steps.json
urai browse "check order status" --remote   # VPS /browser/run
```

```json
[{"action":"goto","url":"https://example.com/login"},
 {"action":"fill","selector":"#email","value":"a@b.com"},
 {"action":"fill_secret","selector":"#password","field":"password"},
 {"action":"click","text":"Sign in"}]
```

MCP: `urai_browse`. Status: `GET /browser/status/<run_id>`.

Requires on the runner: `pip install playwright && playwright install chromium`.
On the VPS the browsers live at `/opt/ms-playwright`, exposed to the API
service via `/etc/systemd/system/urai-api.service.d/playwright.conf`:
`Environment=PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright`.

## 4. Safety policy — auth tasks ALWAYS ask the human first

Non-negotiable rules, enforced in code (`jev/browser.py`):

1. **Urai never stores credentials.** Secrets exist only in process memory,
   only for the run that needs them, auto-wiped after one use or 10 min.
2. **Auth fields pause, never fail.** Any `fill_secret` / `needs_auth` step,
   or `fill` into a password/otp/totp/2fa/pin/cvv field, pauses the run and
   returns `{needs_approval, run_id, fields}`. The run resumes only via
   `POST /browser/approve {"run_id":…, "secrets": {"password": "…"}}`.
3. **Secrets never leak.** Values are masked (`***`) in logs, traces,
   superadmin live view, and persisted state. Only field *names* are shown.
4. **Approval expires** after 10 minutes; expired runs must restart.
5. Agent tool `browse` surfaces the same pause object, so chat/TUI/web can
   prompt the human inline before continuing.
