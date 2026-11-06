# Implementation Plan — Manus-class capabilities for URAI

**Codebase snapshot (verified before planning):**
- 122 tests all pass (`python3 -m pytest tests/ -q`)
- Server: stdlib `BaseHTTPRequestHandler`, SSE via `_sse_chunk()` writing `data: {...}\n\n`
- Agent loop: PLAN→TOOL→OBSERVE→REASON in `jev/agent.py`, regex fenced-block parsing (`TOOL_RE`)
- Tools: `TOOLS` dict in `jev/tools.py`, all run directly on host
- Frontend: vanilla JS IIFE `UraiShell` in `frontend/shell.js`, no bundler

**Gate variables (all default OFF):**
- `URAI_SANDBOX=1` — enables Docker sandbox routing
- `URAI_NATIVE_TOOLS=1` — enables OpenAI function calling
- `URAI_AUTH=1` — enables multi-user auth routes
- `URAI_SESSION_WORKSPACES=1` — scopes file ops to per-session dirs

---

## P0 — Docker Sandbox Per Session

- [ ] 1. Create `sandbox/` directory and Dockerfile.
      Create `/root/urai/sandbox/Dockerfile` based on `ubuntu:22.04`.
      Install: `python3-pip`, `python3-fastapi`, `uvicorn`, `xvfb`, `x11vnc`,
      `websockify`, `google-chrome-stable`, `supervisor`.
      `WORKDIR /app`, `COPY api/ /app/`, `CMD supervisord -c /etc/supervisor/conf.d/supervisord.conf`.
      Files: `sandbox/Dockerfile`
      Verify: `docker build -t urai-sandbox /root/urai/sandbox/` exits 0.

- [ ] 2. Create `sandbox/supervisord.conf` with five programs.
      Programs: `sandbox-api` (uvicorn main:app --host 0.0.0.0 --port 8080),
      `xvfb` (Xvfb :99 -screen 0 1280x800x24),
      `chrome` (google-chrome-stable --headless=new --remote-debugging-port=9222
      --display=:99 --no-sandbox --disable-dev-shm-usage),
      `x11vnc` (x11vnc -display :99 -forever -nopw -rfbport 5900),
      `websockify` (websockify 5901 localhost:5900).
      All `autostart=true`, `autorestart=true`.
      Files: `sandbox/supervisord.conf`
      Verify: file exists and parses as valid INI.

- [ ] 3. Create `sandbox/api/shell_manager.py`.
      `ShellSession` dataclass: `id`, `process` (subprocess.Popen), ring buffer
      (`collections.deque(maxlen=500)`), background reader thread.
      `ShellManager` class: `create_session(sid)`, `get_session(id)`, `send(id, cmd)`,
      `read_output(id, since_line=0)`, `kill(id)`.
      Use `subprocess.Popen(['bash'], stdin=PIPE, stdout=PIPE, stderr=STDOUT, text=True)`.
      Files: `sandbox/api/__init__.py`, `sandbox/api/shell_manager.py`
      Verify: `python3 -c 'import ast; ast.parse(open("sandbox/api/shell_manager.py").read()); print("ok")'`

- [ ] 4. Create `sandbox/api/main.py` FastAPI app.
      Routes: `POST /api/v1/shell/{exec,view,wait,write,kill}`,
      `POST /api/v1/file/{read,write,replace,search,find,upload}`,
      `GET /api/v1/file/download`, `GET /api/v1/supervisor/status`.
      All shell routes delegate to a `ShellManager` instance.
      File routes use stdlib `open()` / `pathlib`.
      Files: `sandbox/api/main.py`
      Verify: `python3 -c 'import ast; ast.parse(open("sandbox/api/main.py").read()); print("ok")'`

- [ ] 5. Create `jev/sandbox.py` — `DockerSandbox` class.
      `create(session_id)`: `subprocess.run(['docker','run','-d','-p','0:8080',
      '-p','0:9222','--name',f'urai-sandbox-{session_id}','urai-sandbox:latest'])`
      Parses container id. Calls `docker port <id> 8080` to get mapped host port.
      `ensure_ready(timeout=30)`: polls `GET /api/v1/supervisor/status` via
      `urllib.request` every 1 s until all programs running or timeout.
      `destroy()`: `subprocess.run(['docker','rm','-f', container_id])`.
      `proxy_call(method, path, **kwargs)`: forwards to `http://127.0.0.1:<port><path>`.
      No docker SDK — stdlib only.
      Files: `jev/sandbox.py`
      Verify: `python3 -c 'from jev.sandbox import DockerSandbox; print("ok")'`

- [ ] 6. Add sandbox tool functions to `jev/tools.py` gated by `URAI_SANDBOX=1`.
      Add `sandbox_exec(cmd, session_id='default')`: checks
      `os.environ.get('URAI_SANDBOX')=='1'`; creates/reuses `DockerSandbox` via
      module-level `_sandboxes: dict`; calls `proxy_call('POST',
      '/api/v1/shell/exec', json={'session_id':session_id, 'cmd':cmd})`;
      falls back to `run_cmd([cmd])` when `URAI_SANDBOX!=1`.
      Add `sandbox_file_read(path, session_id='default')` and
      `sandbox_file_write(path, content, session_id='default')` with same pattern.
      Register in `TOOLS` dict.
      **Risk:** Existing tests must not change — `URAI_SANDBOX` defaults to unset,
      so the fallback path is always taken in tests. Never replace `run_cmd`.
      Files: `jev/tools.py`
      Verify: `python3 -m pytest tests/ -q` (all 122 pass),
      `python3 -c 'from jev.tools import TOOLS; print("sandbox_exec" in TOOLS)'`

---

## P0 — Structured Function Calling in Agent

- [ ] 7. Add `_tools_schema()` to `jev/agent.py`.
      Returns a list of OpenAI function-tool objects (one per tool in `TOOLS`):
      `read_file`, `write_file`, `edit_file`, `run`, `web_search`, `web_fetch`,
      `browse`, `see`, `imagine`, `mcp`.
      Each entry: `{"type":"function","function":{"name":...,
      "description":..., "parameters":{"type":"object","properties":{...},"required":[...]}}}`.
      Files: `jev/agent.py`
      Verify: `python3 -c 'from jev.agent import _tools_schema; s=_tools_schema(); assert len(s)>=8; print(len(s),"tools")'`

- [ ] 8. Add `_plan_schema()` to `jev/agent.py`.
      Three plan tools: `create_plan(title, goal, steps:[{id,description}])`,
      `complete_step(step_id, success, result)`, `deliver_result(answer)`.
      Format matches `_tools_schema()`.
      Files: `jev/agent.py`
      Verify: `python3 -c 'from jev.agent import _plan_schema; p=_plan_schema(); assert len(p)==3; print("plan tools ok")'`

- [ ] 9. Add `event_queue` parameter to `run_agent()` and plan-tool handling.
      Signature change: `run_agent(task, ..., event_queue=None)`.
      When `os.environ.get('URAI_NATIVE_TOOLS','0')=='1'`:
        - call `backend.complete(messages, tools=_tools_schema()+_plan_schema())`
        - parse `response.tool_calls[0]` instead of `TOOL_RE`
      Keep `TOOL_RE` path as else-branch (unchanged).
      Plan tool dispatch (both paths): if `spec['tool'] == 'create_plan'`, emit
      `{'type':'plan', 'title':..., 'goal':..., 'steps':[...]}` to `event_queue`;
      if `'complete_step'`, emit `{'type':'step', 'step_id':..., 'status':..., 'result':...}`;
      if `'deliver_result'`, set answer and break. These never reach `run_tool_call()`.
      Before/after every work-tool call, emit `{'type':'tool', 'function_name':...,
      'args_brief':..., 'status':'calling'|'called', 'brief':...}`.
      **Risk:** `event_queue=None` default means every existing call works unchanged.
      URAI_NATIVE_TOOLS defaults to `'0'` so regex path is always used in tests.
      Files: `jev/agent.py`
      Verify: `python3 -m pytest tests/ -q` (all 122 pass),
      `python3 -c 'import queue,os; os.environ["URAI_FORCE_MOCK"]="1"; from jev.agent import run_agent; q=queue.Queue(); r=run_agent("hello",event_queue=q); print(r["ok"],q.qsize(),"events")'`

---

## P1 — SSE Plan/Step/Tool Events in Server

- [ ] 10. Add `_send_sse_event()` helper and extend `_stream()` in `jev/server.py`.
       Add method `Handler._send_sse_event(self, event_type, data_dict)`:
       writes `b'event: ' + event_type.encode() + b'\ndata: ' + json.dumps(data_dict).encode() + b'\n\n'`
       to `self.wfile` and calls `self.wfile.flush()`.
       Extend `_stream(self, ..., event_queue=None)`: after each backend stream chunk
       (and in the fallback path after each token), drain `event_queue` with
       `while True: try: ev=event_queue.get_nowait(); self._send_sse_event(ev['type'],ev)
       except queue.Empty: break`. Emit `event: message` (add `event:` field) for
       chat content chunks for backward compat — but keep `data:` format
       unchanged so existing clients still work. Note: the existing
       `_sse_chunk` format already works without an `event:` line (EventSource
       default); add `event: message` only when `event_queue` is set so old
       clients see no change.
       Files: `jev/server.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass),
       `python3 -c 'from jev.server import Handler; assert hasattr(Handler,"_send_sse_event"); print("ok")'`

- [ ] 11. Add streaming support to `/agent` POST handler in `jev/server.py`.
       When `body.get('stream')` is true on `/agent`, create a `queue.Queue()`,
       start `run_agent(...)` in a `threading.Thread`, and call `_stream(...,
       event_queue=q)` on the main thread so SSE writes happen on the request
       thread. Pass `event_queue=q` to `run_agent`.
       Non-stream `/agent` path is unchanged (no queue, no SSE).
       Files: `jev/server.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass).

---

## P1 — Plan Panel + Live Action Feed in Frontend

- [ ] 12. Add `PlanPanel` class to `frontend/shell.js`.
       `PlanPanel` creates a fixed-positioned `#plan-panel` div hidden by default.
       `update(data)`: sets title, step counter `(current/total)`, renders `<ul>` of
       steps with icons: ⏳ pending, ▶️ running, ✅ completed, ❌ failed.
       `updateStep(data)`: finds `[data-step-id=X]` element and updates icon + text.
       `close()`: hides the panel.
       Files: `frontend/shell.js`
       Verify: `python3 -c 'with open("frontend/shell.js") as f: assert "PlanPanel" in f.read(); print("ok")'`

- [ ] 13. Add `ToolFeed` class to `frontend/shell.js`.
       `ToolFeed(containerEl)`: takes a DOM element; keeps a `Map` of `tool_call_id → rowEl`.
       `addOrUpdate(data)`: if tool_call_id not in map, creates a row with icon + brief text
       and appends to container; sets `.shimmer` when `data.status==='calling'`,
       removes when `==='called'`.
       Tool icons by function_name: 🔍 web_search, 🌐 web_fetch/browse,
       📄 read_file/write_file/edit_file, 💻 run/sandbox_exec, 🧠 mcp/imagine/see.
       Files: `frontend/shell.js`
       Verify: `python3 -c 'with open("frontend/shell.js") as f: assert "ToolFeed" in f.read(); print("ok")'`

- [ ] 14. Add shimmer + plan-panel + tool-feed CSS to `frontend/app.css`.
       Add at the bottom:
       - `@keyframes shimmer { 0%{opacity:.4} 50%{opacity:1} 100%{opacity:.4} }`
       - `.shimmer { animation: shimmer 1.2s ease-in-out infinite; }`
       - `@media(prefers-reduced-motion:reduce){ .shimmer { animation:none; opacity:.7; } }`
       - `.plan-panel` styles (fixed, z-index 100, bg var(--bg-elev), max-height 40vh,
         hidden by default, `.is-open` shows it)
       - `.plan-steps`, `.plan-step`, `.plan-step-icon` styles
       - `.tool-feed`, `.tool-call`, `.tool-icon`, `.tool-brief` styles
       Files: `frontend/app.css`
       Verify: `python3 -c 'with open("frontend/app.css") as f: c=f.read(); assert "@keyframes shimmer" in c and ".plan-panel" in c; print("ok")'`

- [ ] 15. Wire SSE event handlers in `jev/static/app.html`.
       Locate the `EventSource` listener (inside a `<script>` tag in `app.html`).
       Add handling for named events: when `event.type === 'plan'` call
       `planPanel.update(JSON.parse(event.data))`; when `'step'` call
       `planPanel.updateStep(data)`; when `'tool'` find the current assistant
       message's ToolFeed and call `toolFeed.addOrUpdate(data)`.
       Add `Browser` and `Terminal` toggle buttons to the topbar nav area.
       Instantiate `planPanel = new PlanPanel()` once at page load.
       Files: `jev/static/app.html`
       Verify: `grep -q "planPanel\|PlanPanel" /root/urai/jev/static/app.html && echo ok`

---

## P2 — CDP Screenshot Browser View

- [ ] 16. Add `_cdp_screenshot(cdp_host, cdp_port)` helper to `jev/tools.py`.
       Pure stdlib implementation:
       1. `GET http://{host}:{port}/json` → parse first target's `id`.
       2. Implement minimal WebSocket client with `socket` + `ssl` (stdlib):
          perform HTTP Upgrade handshake (RFC 6455), send
          `{"id":1,"method":"Page.captureScreenshot","params":{"format":"png"}}`
          as a WebSocket frame, read response frame, parse JSON, return
          `{"ok":True,"image_b64":result["data"]}`.
       3. On any error return `{"ok":False,"error":...}`.
       Fallback when CDP port unreachable: return `{"ok":False,"error":"cdp not available"}`.
       Files: `jev/tools.py`
       Verify: `python3 -c 'from jev.tools import _cdp_screenshot; print(_cdp_screenshot.__doc__ or "ok")'`

- [ ] 17. Emit `browser_screenshot` events from agent loop and server.
       In `jev/agent.py`, after `run_tool_call()` returns for any `browse` or
       `sandbox_exec` tool call, if `event_queue` is set and
       `os.environ.get('URAI_SANDBOX')=='1'`:
         call `tools._cdp_screenshot(...)` and push
         `{'type':'browser_screenshot','image_b64':...}` to event_queue.
       In `jev/server.py`'s event-drain loop (step 10), handle
       `type=='browser_screenshot'` by calling `_send_sse_event('browser_screenshot',ev)`.
       Files: `jev/agent.py`, `jev/server.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass).

- [ ] 18. Add `BrowserPanel` class and CSS to frontend.
       `BrowserPanel` creates `#browser-panel` div (fixed right, 400px wide,
       full height, hidden). `show()/hide()` toggles `is-open`. `update(image_b64)`
       sets `<img src='data:image/png;base64,...'>`.
       Wire the Browser toggle button (from step 15) to `browserPanel.show()/hide()`.
       In SSE listener, `event.type === 'browser_screenshot'` → `browserPanel.update(data.image_b64); browserPanel.show()`.
       CSS: `.browser-panel { position:fixed; right:0; top:0; width:400px; height:100vh;
       background:var(--bg-elev); border-left:1px solid var(--border);
       transform:translateX(100%); transition:transform .2s; z-index:200; }
       .browser-panel.is-open { transform:translateX(0); }`.
       Files: `frontend/shell.js`, `frontend/app.css`, `jev/static/app.html`
       Verify: `python3 -c 'with open("frontend/shell.js") as f: assert "BrowserPanel" in f.read(); print("ok")'`

---

## P2 — Multi-user Auth

- [ ] 19. Create `jev/auth.py` (stdlib only).
       `User` dataclass: `id: str, email: str, password_hash: str, created_at: int`.
       `hash_password(pw) → str`: random 16-byte salt, `hashlib.pbkdf2_hmac('sha256',
       pw.encode('utf-8'), salt, 260000)`, returns `salt.hex() + ':' + digest.hex()`.
       `verify_password(pw, stored) → bool`: splits on `:`, re-derives, constant-time compare.
       `register(email, password) → (str, str)`: creates user, returns `(user_id, token)`.
       `login(email, password) → str|None`: looks up email, verifies, returns session token.
       `logout(token)`: deletes session.
       `get_user_by_session(token) → User|None`.
       `load_state()` / `save_state()`: persist `_users` and `_sessions` dicts to
       `data/auth_state.json` (same pattern as `_state` / `STATE_FILE` in server.py).
       Files: `jev/auth.py`
       Verify: `python3 -c 'from jev.auth import register,login,logout; uid,tok=register("a@b.com","pw"); t2=login("a@b.com","pw"); print("auth ok")'`

- [ ] 20. Add auth routes to `jev/server.py` gated by `URAI_AUTH=1`.
       In `do_POST()`, add early (before token gate):
       ```
       if os.environ.get('URAI_AUTH') == '1':
           if p == '/auth/register': ...
           if p == '/auth/login': ...
           if p == '/auth/logout': ...
       ```
       `POST /auth/register {email,password}` → calls `auth.register()`, returns
       `{ok,user_id,token}`.
       `POST /auth/login {email,password}` → calls `auth.login()`, returns `{ok,token}`,
       also sets `Set-Cookie: urai_session=<token>; HttpOnly; SameSite=Strict`.
       `POST /auth/logout` → calls `auth.logout()`, returns `{ok}`, sets expired cookie.
       In `do_GET()`, add:
       `GET /auth/me` → reads `urai_session` cookie from `Cookie` header,
       calls `auth.get_user_by_session()`, returns `{email,id}` or 401.
       When `URAI_AUTH=1`, in `_check_access()`, also accept valid session cookies
       as authenticated (treat same as master key: no free-token decrement).
       **Risk:** When `URAI_AUTH` is unset (default), all this code is skipped.
       Existing tests run with `URAI_AUTH` unset → no change.
       Files: `jev/server.py`, import `from . import auth` conditionally
       Verify: `python3 -m pytest tests/ -q` (all 122 pass),
       `URAI_AUTH=1 python3 -c 'from jev.server import Handler; print("auth routes compiled ok")'`

---

## P3 — Persistent Workspace Per Session

- [ ] 21. Add workspace creation and `get_workspace()` to `jev/sessions.py`.
       In `new_id()`, after generating the id, also call
       `(ROOT/'data'/'workspaces'/sid).mkdir(parents=True, exist_ok=True)`.
       Add `get_workspace(sid: str) -> Path` that returns
       `ROOT / 'data' / 'workspaces' / sid` and creates it if missing.
       **Risk:** `new_id()` currently returns a string — it still does;
       the `mkdir` is a side-effect that is safe to add. Tests call `new_id()`
       but don't assert the absence of the directory.
       Files: `jev/sessions.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass),
       `python3 -c 'from jev.sessions import new_id, get_workspace; sid=new_id(); wp=get_workspace(sid); print(wp.is_dir())'`

- [ ] 22. Add `_set_workspace(path)` to `jev/tools.py` and workspace scoping in server.
       In `jev/tools.py`, add `_set_workspace(path: str)` that sets the
       module-level `WORKSPACE = os.path.realpath(path)` (same pattern as the
       initial assignment at module top). Also update `SAFE_BINARIES` and
       `BLOCKED_RE` reuse — they don't depend on WORKSPACE.
       In `jev/server.py`, in the `/agent` POST handler, if
       `os.environ.get('URAI_SESSION_WORKSPACES')=='1'` and `sid`:
       ```
       old_ws = tool_engine.WORKSPACE
       tool_engine._set_workspace(str(sessions.get_workspace(sid)))
       try:
           result = run_agent(...)
       finally:
           tool_engine._set_workspace(old_ws)
       ```
       **Risk:** This is NOT thread-safe if multiple agent calls run concurrently.
       Mitigate by adding a `_workspace_lock = threading.Lock()` in tools.py
       and acquiring it in the server for the duration of the agent call.
       **Risk:** `URAI_SESSION_WORKSPACES` defaults to unset → existing code path.
       Files: `jev/tools.py`, `jev/server.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass).

- [ ] 23. Add `/session/{id}/files` and `/session/{id}/files/{path}` endpoints.
       In `do_GET()`, add:
       ```python
       if p.startswith('/session/') and '/files' in p:
       ```
       Parse `session_id` and optional `filepath` from the path.
       `/session/{id}/files` → lists files under `data/workspaces/{id}/`
       recursively; returns `{ok, files:[{path,size,modified}]}`.
       `/session/{id}/files/{filepath}` → validates that the resolved path stays
       under the workspace dir (use `Path.resolve()` and assert prefix matches),
       reads the file, returns as `application/octet-stream` with
       `Content-Disposition: attachment; filename=...`.
       Files: `jev/server.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass),
       `grep -n 'session.*files' /root/urai/jev/server.py | head -5`

---

## P3 — Terminal Panel UI

- [ ] 24. Emit `terminal_update` events from agent loop.
       In `jev/agent.py`, in the tool-call section (item 9 above), add: after
       `run_tool_call()` returns for `spec['tool'] in ('run', 'sandbox_exec')`,
       if `event_queue is not None`:
       ```python
       event_queue.put_nowait({
           'type': 'terminal_update',
           'shell_id': (spec.get('args') or {}).get('session_id', 'default'),
           'output': str(out.get('output', ''))[:4000],
           'pid': out.get('pid')
       })
       ```
       Files: `jev/agent.py`
       Verify: `python3 -m pytest tests/ -q` (all 122 pass).

- [ ] 25. Add `TerminalPanel` class to `frontend/shell.js`.
       `TerminalPanel`: constructor creates `#terminal-panel` div with inner
       `.terminal-header` (title + close btn) and `<pre class='terminal-output'>`.
       `append(data)`: appends `data.output` to the pre, scrolls to bottom.
       `clear()`: empties pre. `show()/hide()`: toggles `.is-open`.
       Wire Terminal toggle button to `terminalPanel.show()/hide()`.
       In SSE listener: `event.type === 'terminal_update'` → `terminalPanel.append(data); terminalPanel.show()`.
       Files: `frontend/shell.js`, `jev/static/app.html`
       Verify: `python3 -c 'with open("frontend/shell.js") as f: assert "TerminalPanel" in f.read(); print("ok")'`

- [ ] 26. Add `.terminal-panel` CSS to `frontend/app.css`.
       `.terminal-panel { position:fixed; bottom:0; left:0; right:0; height:300px;
       background:#1a1a1a; border-top:1px solid var(--border-strong);
       z-index:150; display:none; flex-direction:column; }`
       `.terminal-panel.is-open { display:flex; }`
       `.terminal-header { display:flex; align-items:center;
       justify-content:space-between; padding:var(--sp-2) var(--sp-3);
       background:#111; border-bottom:1px solid #333;
       font-size:var(--fs-sm); color:#8a8a8a; }`
       `.terminal-output { flex:1; overflow-y:auto; padding:var(--sp-2) var(--sp-3);
       font-size:.78rem; line-height:1.5; color:#e0e0e0;
       white-space:pre-wrap; word-break:break-all;
       font-family:'Consolas','Monaco','Courier New',monospace; }`
       `body.has-terminal #view-root, body.has-terminal .main-panel
       { padding-bottom:300px; }`
       Files: `frontend/app.css`
       Verify: `python3 -c 'with open("frontend/app.css") as f: assert ".terminal-panel" in f.read(); print("ok")'`

---

## Final Integration Tests

- [ ] 27. Write `tests/test_manus_features.py`.
       Tests (all use `URAI_FORCE_MOCK=1`, no network/Docker needed):
       a. `run_agent("hello", event_queue=queue.Queue())` returns `ok=True` (backward compat).
       b. `URAI_NATIVE_TOOLS=1`: `_tools_schema()` returns list with ≥8 entries,
          each has `type=='function'`.
       c. `_plan_schema()` returns exactly 3 entries.
       d. `get_workspace('test-sid')` returns a `Path`.
       e. `auth.register('x@y.com','pw')` returns `(user_id, token)`; `auth.login('x@y.com','pw')` returns token.
       f. `PlanPanel`, `ToolFeed`, `TerminalPanel`, `BrowserPanel` substrings exist in `shell.js`.
       g. `@keyframes shimmer`, `.plan-panel`, `.terminal-panel`, `.browser-panel`
          exist in `app.css`.
       Files: `tests/test_manus_features.py`
       Verify: `python3 -m pytest tests/test_manus_features.py tests/ -q` (all pass).

---

## Integration Points and Risks

| Integration | Risk | Mitigation |
|---|---|---|
| `run_agent()` new `event_queue` param | Breaks callers with positional args | Add as keyword-only with default `None` |
| `TOOL_RE` vs native function calling | Different parse path | env var gate; TOOL_RE path completely unchanged when `URAI_NATIVE_TOOLS!=1` |
| `WORKSPACE` mutation in server | Thread-unsafe under concurrent requests | `threading.Lock()` wrapping workspace swap |
| `sessions.new_id()` creates dirs | Harmless on existing tests | `exist_ok=True` avoids failures |
| `auth.py` import in server.py | Must not fail when `URAI_AUTH=0` | Conditional import `if os.environ.get('URAI_AUTH')=='1':` inside the handler |
| `sandbox/api/main.py` uses FastAPI | jev/ must stay stdlib-only | FastAPI only in `sandbox/api/` (runs in Docker); never imported from `jev/` |
| `_cdp_screenshot` WebSocket | Complex stdlib WebSocket | Self-contained in tools.py; errors return `{ok:False}` gracefully |
| SSE event ordering | Queue draining must not block stream | `queue.get_nowait()` + `except queue.Empty` loop; no blocking |

## Dependency Order

Items **7-9** (function calling) must precede **10-11** (SSE server integration)
since the server needs `event_queue` to exist in `run_agent`.
Items **12-15** (frontend panels) are independent of backend but require
items **10-11** to produce SSE events to exercise them.
Items **16-18** (CDP screenshot) depend on **5-6** (sandbox) and **17** needs **9**.
Items **19-20** (auth) are independent of all other items.
Items **21-23** (workspace) depend on **sessions.py** changes only.
Items **24-26** (terminal panel) depend on **9** (event_queue in agent).
Item **27** (tests) must be last as it validates everything.
