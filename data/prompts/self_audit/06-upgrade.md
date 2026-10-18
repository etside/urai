# Self-audit prompt 06 — upgrade proposal (run monthly)

Find the next upgrade worth building. Evidence per item:
1. Routing scores (`/agent/routing`): which level/backend has the worst rate with n>=20? Propose the fix.
2. Failure kinds in traces: top `failure_kind` this month? Propose a verifier/budget change.
3. Reference repos: pick ONE (unsloth, bitsandbytes, llmfit, overmind, rea, deepseek-harness, ruflo) — what single portable idea is still missing? Port just that.
4. Small-but-powerful: any same-size quality win unclaimed (imatrix refresh, KV settings, draft model)? Measure first.
5. Cost check: would the upgrade spend GPU/money? Gate it behind bench proof + explicit approval.
6. Write the proposal as: problem (evidence) → smallest diff → verification plan → rollback.

Output: ranked proposals, top one fully specified. Do not build until approved —
except medium/small doc/config fixes, which ship directly.
