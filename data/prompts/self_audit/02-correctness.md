# Self-audit prompt 02 — correctness & benchmarks (run after every change)

Verify Urai still does what it claims. Evidence required per item:
1. `python3 jev/bench_harness.py --tag audit` — 8/8? Paste score line.
2. `python3 jev/bench.py --quick --categories knowledge --tag audit` — knowledge still 1.0?
3. `/agent` trivial task → real (non-mock) answer? Check trace backend is llama-local.
4. Conductor smoke (only if changed): thinker subtasks >= 2, workers succeed?
5. Frontend: `node --check` on extracted JS; handler/ID sweep clean?
6. Any NEW feature without a live verification + docs + report? Name it — it is not done.

Output: scores + one-line verdict per item. Regressions block promotion:
fix or revert before anything else merges.
