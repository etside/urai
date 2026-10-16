# Urai CLI — remote-first usage

Install (nothing heavy downloads locally):

```bash
git clone --depth 1 https://github.com/etside/urai.git ~/.local/share/urai
mkdir -p ~/.local/bin
ln -sf ~/.local/share/urai/bin/urai ~/.local/bin/urai
export PATH="$HOME/.local/bin:$PATH"
urai login 856777            # master key → unlimited, zero cost
```

Guests skip login: 5 free responses per device, then blocked until approved.

## Commands (remote = VPS does the work)

```bash
urai ask --remote "question"                 # one chat turn
urai agent --remote "task" [--plan] [--session NAME] [--no-remember]
urai swarm --remote "task one" "task two" [--workers 3]
urai browse --remote "goal" --steps steps.json
urai chat                                   # local REPL (needs local model)
urai model list | use | download | bench   # model registry ops
urai whoami                                 # quota / approval state
urai skill | plugin | video | see | imagine # skills, plugins, media
urai api --host 0.0.0.0 --port 8777         # serve the API yourself
```

`--plan` proposes file writes without applying; apply from the web UI
(Harness drawer) or `POST /agent/apply` with the master key.
`--session NAME` persists turns server-side; reopen later from any device.

## Config
`~/.config/urai/config.json`: master_key, device_id, remote_url
(default `https://urai.daddyai.online`). Env overrides: `URAI_MASTER_KEY`,
`URAI_DEVICE_ID`, `URAI_REMOTE_URL`, `URAI_REMOTE=1` (force remote).
