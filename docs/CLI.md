# Urai CLI — remote-first usage

`urai` (alias `jev`) is stdlib-only and runs from a checkout with no install:

```bash
git clone --depth 1 https://github.com/etside/urai.git ~/.local/share/urai
mkdir -p ~/.local/bin
ln -sf ~/.local/share/urai/bin/urai ~/.local/bin/urai
export PATH="$HOME/.local/bin:$PATH"
urai login 856777            # master key → unlimited, zero cost
```

Guests skip login: 5 free responses per device, then blocked until approved.
Every command works **locally** (needs the local model/API) or with `--remote`
against the VPS (`https://urai.daddyai.online`). Remote needs `urai login`.

## Chat & agents

```bash
urai chat [--remote] [-v]                     # REPL (local streams tokens)
urai ask "question" [--remote] [--model urai|cyberurai] [--max-tokens N]
urai agent "task" [--plan] [--session NAME] [--no-remember] \
      [--remote] [--model urai|cyberurai] [-v]
urai swarm "t1" "t2" [--workers 3] [--mode parallel|conductor] \
      [--remote] [--model urai|cyberurai]
urai apply PROPOSALS.json [--remote]           # land --plan proposals
                                               # (alias: urai agent apply FILE)
```

- Local `ask` is a **lightweight one-shot**: it runs `nlp.analyze` + `vibe.plan`,
  prepends the style directive, calls the local model once, and prints plain
  text (no agent loop, no JSON dump).
- Local `agent` persists/reads turns via `jev.sessions` when `--session` is
  given; `--no-remember` skips writing.
- `--plan` records file writes instead of applying them. Save the returned
  `proposals` array to a file and land it with `urai apply file.json` (or feed
  it on stdin with `-`). This POSTs to `/agent/apply` with the master key and
  prints one line per proposal.
- `urai swarm --mode conductor` runs the Thinker→Workers→Verifier orchestration
  (`/agent/swarm` with `{"mode":"conductor"}`).
- `chat`/`agent` accept `-v`/`--verbose` to print a compact `urai` analysis
  summary from the server response (`[nlp] …` and `[vibe] …` lines). Pass it
  twice (`-vv`) to also dump the full `vibe.directive` style contract. When the
  server omits the `urai` block (older server) it prints `[nlp] unavailable`.

## Models & serving

```bash
urai model list                              # registry + availability + bench
urai model download <id>                     # fetch GGUF from HF into model/base
urai model use <id>                          # set active model (restarts server)
urai model bench [--id ID]                   # llama-bench row for a model
urai serve start|stop|status|restart [--model ID] [--ctx N] [--port P] [--spec ngram-mod] [--all]
urai gpu                                     # detect GPU + offload policy
urai version
urai teacher status|test                     # external teacher backend check
```

`serve stop` stops the chat/vision server **and** the embedding server
(`--all` makes the intent explicit and is accepted for both `stop` and
`restart`). `serve restart` stops both, then starts the selected (or active)
model, auto-passing `--mmproj` for vision models and taking the embedding path
for `kind=embedding`.

## Vision, media & embeddings

All of these accept `--remote`:

```bash
urai see IMAGE [QUESTION] [--max-tokens N] [--remote]      # /see
urai imagine "prompt" [-o out.png] [--steps N] [--seed N] [--remote]
                                                           # /v1/images/generations
urai image "prompt" [-o out.png] [--steps N] [--seed N] [--remote]  # alias of imagine
urai embed "text" ... [--remote]                           # /v1/embeddings
urai video "prompt" [-o out.mp4] [--duration 4] [--remote]
urai evaluate "task" --expect a,b [--remote]               # /evaluate
urai studio                                    # media profiles / providers
urai studio image|video "prompt" [--out F] [--remote]      # dispatch to imagine/video
urai studio see IMAGE [--remote]                # dispatch to see
```

`studio` is the CLI counterpart of the webapp's **Studio** view: `status`
lists the media profiles/providers the API advertises (`/v1/media/profiles`),
and `image`/`video`/`see` route to the same code paths as `imagine`/`video`/
`see` (local by default, `--remote` for the VPS).

## Skills, plugins, profile, mood

```bash
urai skill list                        # list capability packs
urai skill show NAME                   # print the pack's SKILL.md
urai skill add NAME [--desc TEXT]      # scaffold skills/NAME/SKILL.md
urai skill enable|disable NAME         # toggle data/skills_state.json
urai plugin list|enable|disable|serve NAME
urai profile [--ident ID] [--set key=value]   # sticky user preferences
urai vibe on|off|status                 # sentiment-conditioned generation
urai tasks [list|add "task" [--every N]|run --id ID|rm --id ID] [--remote]
urai theme light|dark|system
```

- `profile --set` accepts `formality`, `warmth`, `verbosity`, `humor`,
  `technical_depth`, `emoji`, and `language` (default identity = device id).
- `vibe on|off` persists `URAI_VIBE` in the config and exports it for local
  runs.
- `tasks` drives scheduled agent jobs via `/agent/jobs` (`list`, `add`, `run`,
  `rm`→delete).
- `theme` stores the UI preference (consumed by the web app / clients).

## Remote & account

```bash
urai login [KEY] [--url URL]   # save master key (masked in output)
urai logout                    # forget saved credentials
urai whoami                    # quota / approval state
urai browse "goal" [--steps steps.json] [--remote]
urai mcp                       # MCP stdio server (Claude/opencode tools)
urai api [--host ADDR] [--port P]   # serve the API + web playground (:8777)
```

## Config

`~/.config/urai/config.json` — parent dir `0700`, file `0600`:

- `master_key` (never echoed; masked as `85******77`)
- `device_id`
- `remote_url` (default `https://urai.daddyai.online`)
- `vibe` (bool), `theme`

Env overrides: `URAI_MASTER_KEY`, `URAI_DEVICE_ID`, `URAI_REMOTE_URL`,
`URAI_REMOTE=1` (force remote), `URAI_VIBE=0` (disable vibe-text).
