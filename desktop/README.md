# Urai Desktop

Electron shell for **Urai AI Studio** — one window, no browser chrome, Windows and Linux.

The desktop app is a thin Chromium shell around the Urai API server:

```
Electron window  ──►  http://127.0.0.1:8777  ──►  python -m jev.cli api
```

## Run from source

```bash
pip install -e .          # from the repo root
cd desktop
npm install
npm start
```

The shell finds the repo automatically (`../jev/cli.py`). If you installed
Urai elsewhere, set `URAI_HOME`:

```bash
URAI_HOME=/opt/urai npm start
```

## Build installers

```bash
cd desktop
npm install
npm run dist           # host platform
npm run dist:linux     # AppImage + .deb
npm run dist:win       # NSIS installer + portable .exe
```

Artifacts land in `desktop/dist/`.

CI builds both platforms on every `v*` tag — see
`.github/workflows/desktop.yml`.

## Configuration

`~/.urai/desktop.json` (all fields optional):

```json
{
  "python": "/usr/bin/python3",
  "home": "/opt/urai",
  "port": 8777,
  "noServer": false
}
```

| Env | Meaning |
|---|---|
| `URAI_PYTHON` | Python interpreter to use |
| `URAI_HOME` | Directory containing `jev/` |
| `URAI_PORT` | Preferred port (falls back to a free one) |
| `URAI_NO_SERVER=1` | Attach to an already-running server |

If the backend cannot start, the window shows a setup screen with the
captured backend log and a Retry button.

## Notes

- No Node integration in the renderer; only `retry`, `log`, `open` are exposed.
- External links always open in the system browser.
- Closing the window stops the backend it started (SIGTERM, then SIGKILL).
- The app is unsigned. Windows SmartScreen will warn on first run; Linux
  AppImage needs `chmod +x`.
