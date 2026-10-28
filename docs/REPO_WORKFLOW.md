# Urai Repo Workflow

How to update the codebase — from your laptop, from the VPS, or via CI — and
keep everything in sync without conflicts.

---

## Everyday flow

```
Edit code (laptop or VPS)
  ↓
Test locally:  python3 scripts/smoke_urai.py
  ↓
Commit + push to GitHub
  ↓
VPS pulls the update
  ↓
systemctl restart urai-api
```

---

## 1. Edit from your laptop → push → VPS pulls

```bash
# On your laptop
git clone https://github.com/etside/urai.git
cd urai

# Make changes, then:
python3 scripts/smoke_urai.py          # quick offline sanity check (~6s)
git add <specific files>
git commit -m "feat: describe your change"
git push

# On the VPS
ssh -i ~/.ssh/urai_do root@<VPS_IP>
cd /opt/urai
sudo -u urai bash scripts/repo_sync.sh   # pulls + compile-checks urai
sudo systemctl restart urai-api
```

`repo_sync.sh` does: `git pull --ff-only` + `py_compile` of core modules.
If the pull fails (diverged history), fix it manually — the script won't force-reset.

---

## 2. Edit directly on the VPS

```bash
ssh -i ~/.ssh/urai_do root@<VPS_IP>
su - urai
cd /opt/urai

# Make changes
nano jev/server.py

# Test the change doesn't break imports
python3 -m py_compile jev/server.py && echo OK

# Commit from the VPS
git add jev/server.py
git commit -m "fix: describe the fix"
git push
sudo systemctl restart urai-api
```

---

## 3. Push multiple files in one atomic commit (no 409 conflicts)

When CI or a script needs to commit several files at once, use the Git Data API
script. This avoids race conditions from parallel commits:

```bash
bash scripts/gh_batch_commit.sh etside/urai main "feat: add voice and vibe" \
  /tmp/voice.py:jev/voice.py \
  /tmp/vibe.py:jev/vibe.py \
  /tmp/registry.json:model/registry.json
```

Each file is uploaded as a blob in parallel; the tree + commit is one atomic
API call. Requires `gh` CLI (already authenticated) and `jq`.

---

## 4. What CI runs automatically

Every push to `main` triggers two workflows:

| Workflow | What it checks | Time |
|---|---|---|
| `ci.yml` | `py_compile` all `.py` files + offline smoke test | ~1 min |
| `urai-ci.yml` | Lint, all import checks, Python 3.10 compat, smoke test | ~3 min |

If either fails, the push is "red" — check **Actions** tab on GitHub.
Fix the error, push again. Never `--no-verify` or skip these.

To run the same checks locally before pushing:
```bash
python3 scripts/smoke_urai.py
find . -name '*.py' -not -path './.git/*' | xargs python3 -m py_compile
```

---

## 5. Scheduled automation (no action needed)

These run automatically — just make sure the GitHub secrets are set:

| Workflow | Schedule | What it does |
|---|---|---|
| `urai-selfimprove.yml` | Every Sunday 03:00 UTC | Probes VPS, mines failures → new distill tasks, commits to `data/raw_tasks/selfimprove/` |
| `urai-bench.yml` | Manual dispatch | Benchmarks models, writes to `eval/reports/` |
| `desktop.yml` | On version tags (`v*`) | Builds Windows/Linux desktop installers |
| `build.yml` | On version tags (`v*`) | Builds llama.cpp + model bundle, creates GitHub Release |
| `pages.yml` | On push to `main` | Deploys the Studio shell to GitHub Pages |

Required GitHub secrets:
- `URAI_MASTER_KEY` — for self-improve and bench workflows to hit the VPS
- `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` — for Modal cloud GPU training (optional)

Required GitHub variables:
- `URAI_BASE_URL` — your VPS URL e.g. `https://urai.example.com`

Set them at: `github.com/etside/urai → Settings → Secrets and variables → Actions`

---

## 6. Cutting a release

```bash
# 1. Update CHANGELOG.md — add the new version section
# 2. Tag the commit
git tag v3.1.0
git push origin v3.1.0

# GitHub Actions (desktop.yml + build.yml) build the artifacts automatically.
# Monitor progress:
gh run list --workflow desktop.yml
gh run list --workflow build.yml

# Once done, the release appears at:
# https://github.com/etside/urai/releases
```

The release bundle includes: Windows installer + portable, Linux AppImage + .deb,
and the llama.cpp + model weights bundle (split at 1.9 GB).

To reassemble the model bundle after downloading:
```bash
python3 scripts/assemble_release.py <download-dir>
```

---

## 7. Branch strategy

| Branch | Purpose |
|---|---|
| `main` | Production. CI must be green before merging. |
| `feat/*` | New features — PR into main. |
| `fix/*` | Bug fixes — PR into main. |

Direct pushes to `main` are allowed for solo work but discouraged for changes
that affect serving code (use a PR so CI runs first).

---

## 8. Adding a new Python module

1. Create `jev/yourmodule.py`
2. Add an import in the CI smoke test (`urai-ci.yml`) under "Import smoke test"
   so it's compile-checked on every push:
   ```python
   import jev.yourmodule
   ```
3. If it adds a CLI command, document it in `docs/CLI.md`
4. If it adds an API route, document it in `docs/API.md`
5. Run `python3 scripts/smoke_urai.py` before committing

---

## 9. Adding or updating a skill

```bash
# Skills live in skills/<name>/
ls skills/

# Each skill has at minimum:
#   skills/<name>/skill.json     — metadata (name, description, tools)
#   skills/<name>/README.md      — usage instructions

# Test a skill manually:
urai ask --skill zen-coder "write a binary search in Python"
```

---

## Common mistakes

| Mistake | Fix |
|---|---|
| Push broke CI | `python3 -m py_compile jev/*.py` locally first |
| VPS out of sync after a force-push | `git fetch origin && git reset --hard origin/main` (only if you're sure) |
| Two people pushed at the same time → conflict | `git pull --rebase` then push |
| Committed `.env` or a secret | Rotate the secret immediately, then `git filter-repo` to scrub history |
| Service won't restart after update | Check `journalctl -u urai-api -n 30` — usually a syntax error in a `.py` file |
