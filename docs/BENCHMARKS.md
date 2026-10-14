# Urai benchmarks — measured, reproducible

Every row below is produced by `jev/bench.py` against the **live**
system (`--base https://urai.daddyai.online`, master key = cost 0).
Method: knowledge = substring match (12 Qs); math = exact numeric
match with 3-sample majority vote (12 Qs); code = generated `solve()`
EXECUTED against tests, best-of-3 by pass (6 tasks). No cherry-picking:
the harness reports every item. Re-run anytime:
`Actions → Urai Bench → Run workflow`.

| report | started (UTC) | knowledge | math | code | calls | wall time |
|---|---|---|---|---|---|---|
| `bench-bench-first.json` | 2026-10-14T23:19:15Z | 1.0 | 0.833 | 1.0 | 66 | 292.2s |
| `bench-coder05-kv8fa.json` | error: 'list' object has no attribute 'get' | - | - | - | - | - |
| `bench-coder05-plain.json` | error: 'list' object has no attribute 'get' | - | - | - | - | - |
| `bench-qwen25vl.json` | error: 'list' object has no attribute 'get' | - | - | - | - | - |

Honest framing: these scores measure **this deployment** (Qwen3-4B Q4_K_M,
CPU, self-consistency + verifier re-rank on). They show the system working
correctly — not parity with frontier models 10-100x its size. The methods
that move these numbers (majority vote, exec-pass pick, CoT routing) are
exactly what `jev/bench.py` and `run_agent(consistency=N)` implement.
