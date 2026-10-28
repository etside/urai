# Urai CLI

The `urai` binary is a stdlib-only Python CLI. It talks to your local API
(`127.0.0.1:8777`) by default, or to a remote Urai instance with `--remote`.

## Install

```bash
git clone --depth 1 https://github.com/etside/urai.git ~/.local/share/urai
mkdir -p ~/.local/bin
ln -sf ~/.local/share/urai/bin/urai ~/.local/bin/urai
export PATH="$HOME/.local/bin:$PATH"
```

or, from a checkout:

```bash
pip install -e .
urai --help
```

## Quick start

```bash
urai api                 # start the API + Studio on :8777
urai studio              # same, but opens the Studio in your browser
urai tui                 # terminal UI over the same API
urai ask "explain async/await"
```

`urai studio` starts the server in the background only if `/health` is not
already answering. `urai tui` expects a running API and prints how to start one
if it cannot connect.

## Local commands

```bash
urai chat                     # interactive REPL (needs `urai serve start`)
urai ask "question"           # one-shot answer
urai agent "multi-step task"  # plan / tool / verify loop
urai vibe "build a todo app" --workspace ./todo
urai vibe "add tests" --plan  # propose writes, do not apply
```

`urai agent --plan` proposes file writes without applying them. Apply from the
Studio or with `POST /agent/apply` using the master key.

## Studio & terminal UI

```bash
urai studio [--port 8777] [--host 127.0.0.1] [--no-open]
urai tui
```

The TUI reads and writes through the HTTP API, so it sees the same sessions,
models and keys as the web Studio.

TUI commands:

| Command | Action |
|---|---|
| `/help` | show help |
| `/clear` | clear the conversation |
| `/model <id>` | change model |
| `/key <token>` | use an API token for this session |
| `/save <file>` | write the transcript as JSON |
| `/quit` | exit |

Anything else is sent to `/v1/chat/completions`.

## API keys

```bash
urai key list
urai key create laptop            # unlimited quota, printed once
urai key create ci --quota 1000   # 1000 requests
urai key revoke urai_xxx          # full token or unique prefix
```

Keys are stored in `data/api_tokens.json` (git-ignored). The full token is
printed only at creation; `key list` shows a masked form and the full id used
for revocation.

`--remote` sends the same operations to the configured remote instance.

## Knowledge wiki

```bash
urai wiki add "Deploy" "Caddy + systemd on :443" --category projects
urai wiki search "deploy"
urai wiki get "Deploy"
urai wiki list [--category projects]
```

`wiki add` reads stdin when neither a body argument nor `--content` is given:

```bash
cat notes.md | urai wiki add "Meeting notes" --category sessions
```

Pages live under `data/workspace/{concepts,entities,projects,sessions}/` and
support `[[wikilinks]]`.

## Named agents

```bash
urai agents list
urai agents create Scout \
  --instructions "Track AI news and summarise it" \
  --tools web_search,wiki_search \
  --schedule daily@09:00
urai agents run <id> "What changed this week?"
urai agents delete <id>
```

Agents keep private notes (`data/agents/<id>_notes.md`) and run history.

## Routines

Scheduled recurring prompts, executed by the server scheduler.

```bash
urai routines list
urai routines create Morning --prompt "Summarise my day" --schedule daily@08:00
urai routines run <id>
urai routines delete <id>
```

Schedule strings: `manual`, `daily@HH:MM`, `every:<seconds>`.

## Models & serving

```bash
urai model list
urai model download qwen3-4b
urai model use qwen3-4b
urai serve start --model qwen3-4b --ctx 8192
urai serve status
urai serve stop
```

`--ctx` sets the llama.cpp context window. The Studio's `∞ No limit` pill
requests up to 8192 output tokens; the real ceiling is the server's `--ctx`.

## Media & vision

```bash
urai see screenshot.png "what is wrong with this UI?"
urai imagine "a brass owl on a rainy rooftop" -o owl.png
urai embed "text to vectorise"
urai video "a slow pan over a coastline" -o clip.mp4
```

## Remote mode

```bash
urai login [key]        # save a master key for remote use
urai whoami             # show remote status / quota
urai logout

urai ask --remote "question"
urai agent --remote "task" [--plan] [--session NAME] [--no-remember]
urai swarm --remote "task one" "task two" [--workers 3]
urai browse --remote "goal" --steps steps.json
```

Guests skip login: a small number of free responses per device
(`URAI_FREE_LIMIT`), then blocked until a master approves the device.

## Configuration

`~/.config/urai/config.json`:

| Key | Meaning |
|---|---|
| `master_key` | saved master key |
| `device_id` | stable device identity |
| `remote_url` | remote base URL |

Environment overrides:

| Variable | Meaning |
|---|---|
| `URAI_MASTER_KEY` | master key (takes precedence over config) |
| `URAI_DEVICE_ID` | device identity |
| `URAI_REMOTE_URL` | remote base URL |
| `URAI_REMOTE=1` | force remote mode |
| `URAI_API` | local API base (e.g. `http://127.0.0.1:8799`) |
| `URAI_MODEL` | default model for `tui` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Urai API not reachable` | run `urai api` or `urai studio` |
| `[error: … is the model server up?]` | `urai serve start` |
| `401 master key required` | set `URAI_MASTER_KEY` or `urai login` |
| `429 rate_limit_exceeded` | raise `URAI_RATE_LIMIT` / `URAI_RATE_WINDOW` |
