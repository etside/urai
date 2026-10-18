# Self-audit prompt 05 — docs & drift (run after every feature)

Docs are product. Evidence per item:
1. Every new endpoint in `docs/API.md` AND served in `/v1/docs`? Diff them.
2. Every new capability in `docs/HARNESS.md`? Every new skill in `urai skill list` output?
3. README header still true (model, rows, GPU state)? Fix stale numbers.
4. `docs/INDEPENDENCE.md` stages: did any stage advance (rows banked, adapter landed)? Update counts.
5. Dead docs: any doc describing removed behavior? Delete or correct.
6. Frontend: any button/panel without a working backend route? Click-test each drawer tab.

Output: drift list (doc:line → fix) or IN-SYNC. Commit doc fixes with code.
