#!/usr/bin/env python3
"""
Urai Continuous Self-Training Loop (no Modal)
VPS (Tailscale node) orchestrator:
  1. gh + BeautifulSoup scrape latest training patterns (Kaggle, Tailscale, LiteLLM)
  2. Generate synthetic distill data from those patterns
  3. Merge into distill-master.jsonl
  4. Validate with soup data inspect
  5. Dispatch training to Kaggle via gh CLI (push dataset + trigger notebook)
  6. Log everything

Run once:    python3 self_train_loop.py
Run daemon:  python3 self_train_loop.py --daemon --interval 6
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent          # /home/kp/urai-work/urai
DATA_DIR = ROOT.parent / "data" / "verified"               # /home/kp/urai-work/data/verified
LOG      = ROOT / "scripts" / "self_train_log.jsonl"
SCRAPER  = ROOT / "scripts" / "gh_soup_scraper.py"
GEN_DATA = ROOT / "scripts" / "distill" / "gen_missing_data.py"


def log(msg: str, level: str = "info"):
    entry = {"ts": datetime.now().isoformat(), "level": level, "msg": msg}
    with open(LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    prefix = {"info": "✓", "warning": "⚠", "error": "✗"}.get(level, "·")
    print(f"[{entry['ts'][:19]}] {prefix} {msg}")


def run(cmd: list, cwd=None, timeout=300) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(cwd or ROOT), timeout=timeout)
    return r.returncode, r.stdout, r.stderr


# ── Steps ────────────────────────────────────────────────────────────────────

def step_scrape_github():
    """Use gh auth + BeautifulSoup to scrape best training code from GitHub."""
    log("Scraping GitHub for Kaggle/Tailscale/LiteLLM training patterns...")
    code, out, err = run([sys.executable, str(SCRAPER)], timeout=180)
    if code != 0:
        log(f"Scraper error: {err[:200]}", "warning")
        return False
    scraped = DATA_DIR / "distill-ghsoup.jsonl"
    rows = sum(1 for _ in open(scraped)) if scraped.exists() else 0
    log(f"Scraped {rows} rows from GitHub -> distill-ghsoup.jsonl")
    return True


def step_generate_base_data():
    """Generate synthetic distill data (vision, JS/TS, multimodal, benchmark)."""
    log("Generating base distill data...")
    code, out, err = run([sys.executable, str(GEN_DATA)], timeout=120)
    if code != 0:
        log(f"Data gen error: {err[:200]}", "error")
        return False
    master = DATA_DIR / "distill-master.jsonl"
    rows = sum(1 for _ in open(master)) if master.exists() else 0
    log(f"Master dataset: {rows} rows")
    return rows > 0


def step_merge_scraped():
    """Merge distill-ghsoup.jsonl into distill-master.jsonl."""
    import hashlib

    def hsh(text):
        return hashlib.md5(text.encode()).hexdigest()[:16]

    master_path = DATA_DIR / "distill-master.jsonl"
    soup_path = DATA_DIR / "distill-ghsoup.jsonl"

    if not soup_path.exists():
        log("No scraped data to merge", "warning")
        return True

    existing = {}
    if master_path.exists():
        for line in open(master_path):
            line = line.strip()
            if line:
                r = json.loads(line)
                existing[r.get("content_hash", "")] = r

    added = 0
    for line in open(soup_path):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        h = r.get("content_hash", hsh(r.get("prompt", "") + r.get("completion", "")))
        if h not in existing:
            existing[h] = r
            added += 1

    with open(master_path, "w") as f:
        for r in existing.values():
            f.write(json.dumps(r) + "\n")

    log(f"Merged: +{added} new rows from gh-soup. Master now {len(existing)} rows.")
    return True


def step_soup_validate():
    """Validate master dataset with soup data inspect (skip if soup CLI not installed)."""
    import shutil
    master = DATA_DIR / "distill-master.jsonl"
    if not shutil.which("soup"):
        log("soup CLI not found — skipping soup validate step (install soup or ignore)")
        return True
    code, out, err = run(["soup", "data", "inspect", str(master)], timeout=60)
    snippet = (out + err)[:150].replace("\n", " ").strip()
    log(f"soup validate: {snippet}")
    return True


def step_dispatch_kaggle():
    """
    Dispatch training to Kaggle:
    - Push distill-master.jsonl as a Kaggle dataset update via kaggle CLI
    - The Kaggle notebook (urai_kaggle_setup.txt) reads from sherikhtj/urai-distill-v0-2
    - Manual trigger via kaggle API or gh workflow dispatch
    """
    log("Preparing Kaggle training dispatch...")

    # Check kaggle CLI
    code, out, err = run(["kaggle", "--version"], timeout=10)
    if code != 0:
        # Try pip install
        log("kaggle CLI not found, installing...", "warning")
        subprocess.run(["pip3", "install", "kaggle", "--break-system-packages", "-q"],
                       capture_output=True)
        code, out, err = run(["kaggle", "--version"], timeout=10)

    if code == 0:
        log(f"Kaggle CLI ready: {out.strip()}")
        # Push dataset to Kaggle
        master = DATA_DIR / "distill-master.jsonl"
        rows = sum(1 for _ in open(master)) if master.exists() else 0
        log(f"Ready to push {rows} rows to Kaggle dataset sherikhtj/urai-distill-v0-2")
        # Actual push requires ~/.kaggle/kaggle.json credentials
        kaggle_creds = Path.home() / ".kaggle" / "kaggle.json"
        if kaggle_creds.exists():
            # Create dataset-metadata.json for push
            meta_path = DATA_DIR / "dataset-metadata.json"
            meta = {
                "title": "urai-distill-master",
                "id": "sherikhtj/urai-distill-v0-2",
                "licenses": [{"name": "CC0-1.0"}]
            }
            meta_path.write_text(json.dumps(meta))
            code, out, err = run(
                ["kaggle", "datasets", "version", "-p", str(DATA_DIR),
                 "-m", f"Auto-update: {rows} rows {datetime.now().strftime('%Y-%m-%d')}"],
                timeout=120
            )
            if code == 0:
                log("Kaggle dataset pushed successfully")
                return True
            else:
                log(f"Kaggle push failed: {err[:200]}", "warning")
        else:
            log("~/.kaggle/kaggle.json not found — add Kaggle API credentials to enable auto-push", "warning")
    else:
        log("Kaggle CLI unavailable — manual notebook trigger needed", "warning")

    # Fallback: trigger via gh workflow dispatch if .github/workflows exists
    workflows = list((ROOT / ".github" / "workflows").glob("*kaggle*")) if (ROOT / ".github" / "workflows").exists() else []
    if workflows:
        wf = workflows[0]
        log(f"Triggering gh workflow: {wf.name}")
        code, out, err = run(
            ["gh", "workflow", "run", wf.name, "--ref", "main"],
            timeout=30
        )
        if code == 0:
            log(f"gh workflow triggered: {wf.name}")
            return True
        log(f"gh workflow trigger failed: {err[:150]}", "warning")

    return False


def step_litellm_test():
    """Quick LiteLLM connectivity test against Urai API."""
    log("Testing Urai API via LiteLLM...")
    test_script = """
import sys
try:
    import litellm
    litellm.api_base = "http://52.66.18.45:8777/v1"
    litellm.api_key = "urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY"
    resp = litellm.completion(
        model="openai/urai",
        messages=[{"role": "user", "content": "Say OK"}],
        timeout=10, max_tokens=10,
        base_url="http://52.66.18.45:8777/v1"
    )
    print("API OK:", resp.choices[0].message.content[:50])
except Exception as e:
    print(f"API unreachable (expected if training): {e}", file=sys.stderr)
    sys.exit(0)  # not a fatal error
"""
    code, out, err = run([sys.executable, "-c", test_script], timeout=20)
    result = (out + err).strip()[:120]
    log(f"LiteLLM test: {result}")
    return True


# ── Cycle ────────────────────────────────────────────────────────────────────

def run_cycle():
    log("=" * 55)
    log("Urai self-training cycle START")

    step_scrape_github()        # gh + BeautifulSoup scrape
    step_generate_base_data()   # synthetic data gen
    step_merge_scraped()        # merge scraped into master
    step_soup_validate()        # soup data inspect
    step_dispatch_kaggle()      # push to Kaggle + trigger training
    step_litellm_test()         # verify API still alive

    log("Urai self-training cycle COMPLETE")
    log("=" * 55)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--interval", type=int, default=6, help="Hours between cycles")
    args = parser.parse_args()

    if args.daemon:
        log(f"Daemon mode: every {args.interval}h")
        while True:
            run_cycle()
            wake = datetime.fromtimestamp(time.time() + args.interval * 3600)
            log(f"Next cycle at {wake.strftime('%Y-%m-%d %H:%M')}")
            time.sleep(args.interval * 3600)
    else:
        run_cycle()


if __name__ == "__main__":
    main()
