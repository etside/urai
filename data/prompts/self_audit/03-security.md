# Self-audit prompt 03 — security & secrets (run weekly)

Hunt leaks and over-permissions. Evidence for every claim:
1. `git ls-files` — any `.gguf/.safetensors/.key/.pem`, `*secret*`, `*token*` tracked? Must be none.
2. Service files: any inline `KEY=`/`TOKEN=` values? Must use EnvironmentFile 600.
3. Repo secrets list: names only — every name still needed? Drop dead ones.
4. Local history: any `dop_v1`/`gho_` markers in opencode/openclaw logs? If live: rotate first, then clean.
5. Jail test: `/tools read_file ../../etc/passwd` refused? `/agent/apply` without master → 403?
6. Deps: `pip list` for modal/kaggle venvs — unpinned majors that could break CI?

Output: leak list (file:line) or CLEAN. Rotate-then-clean for any live secret
found outside vaults. Commit the fix, never the secret.
