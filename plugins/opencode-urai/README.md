# Urai plugin for opencode

Exposes Urai (local AI) to opencode sessions as 7 tools: `urai_ask`,
`urai_agent`, `urai_see`, `urai_imagine`, `urai_embed`, `urai_model`,
`urai_evaluate`. The tools shell out to the `urai` CLI, so they work whether
or not the model servers are running (server-backed features error clearly
when their runner is down).

## Install

```bash
# project-level
cp plugins/opencode-urai/urai.js <your-project>/.opencode/plugins/
# or global
cp plugins/opencode-urai/urai.js ~/.config/opencode/plugins/
```

Needs the CLI (repo `install.sh`, default `~/.local/share/urai`) or set
`URAI_HOME=/path/to/urai` in opencode's env.

## Verify

In opencode, ask the model to list tools or run `/tools` — the seven
`urai_*` tools appear. Quick check: "use urai_ask to say hi".

Ref: https://opencode.ai/docs/plugins/
