# Urai safety notice (adapted honesty-first: what the sandbox is and is not)

Urai executes model-generated commands and file writes, loads local plugins
and skills, and reaches the network (keyless fetch/search). Treat it as a
capable junior engineer with strict but narrow guardrails — not a sandbox.

## What the guardrails do
- Filesystem jail: `read/write/edit` confined under the workspace
  (`JEV_WORKSPACE`, default repo root). `..` escapes refused.
- Command allowlist: only listed read-only/safe binaries run, argv-based
  (no shell), timeout-guarded, `run` блокs `rm/mv/dd/>/mkfs/fork-bombs`.
  Git limited to read-only subcommands. Externalized in `policy.json`.
- Plan mode: writes become proposals; `/agent/apply` needs the master key.
- Browser: private/local hosts blocked; auth fields pause for approval.
- Secrets: analyzer redacts key-like values; verifier hard-fails leaks.
- Backups: nightly data snapshots (models re-downloadable, excluded).

## What they do NOT do
- No container/VM isolation: allowed commands run as the service user with
  its full reachable filesystem except the jail, network, and CPU.
- Approval prompts and allowlists reduce risk but cannot prevent damage
  from anything the policy permits. Review toolpacks, plugins, jobs and
  proposed diffs before approving.
- Do not expose credentials to untrusted prompts, plugins, or web content.
- Keep backups; prefer disposable environments for untrusted workloads.

Run with least privilege. No warranty.
