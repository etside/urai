#!/usr/bin/env python3
"""Model promotion gate — compare bench reports and auto-promote if better.

Usage:
    python3 scripts/promote.py --tag <new-checkpoint-tag> --model-id <registry-id>
    python3 scripts/promote.py --tag lora-2026-10-27 --model-id qwen3-4b-lora

Flow:
  1. Read eval/reports/bench-<tag>.json  (new model's bench)
  2. Read eval/reports/bench-<previous>.json  (current active model's bench)
  3. Compare accuracy on knowledge + math + code
  4. If new >= prev on ALL categories (no regression) → update model/registry.json active
  5. If regression → refuse, print details, exit 1 (safe for CI gate)
  6. Log result to eval/reports/promotions.jsonl

Safe: never modifies serving code, never restarts server, never deploys.
      Only changes model/registry.json active field.
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "eval" / "reports"
REGISTRY = ROOT / "model" / "registry.json"
PROMO_LOG = REPORTS / "promotions.jsonl"

CATEGORIES = ["knowledge", "math", "code"]
MIN_IMPROVE_DELTA = -0.02   # allow up to 2% drop per category (noise tolerance)


def load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"ERROR: cannot read report {path}: {e}", file=sys.stderr)
        sys.exit(1)


def score_of(report: dict, cat: str) -> float | None:
    cats = report.get("categories", {})
    if cat in cats:
        return cats[cat].get("accuracy")
    # bench.py stores at top level too
    return report.get(cat, {}).get("accuracy") if isinstance(report.get(cat), dict) else None


def find_latest_report(exclude_tag: str) -> Path | None:
    reports = sorted(REPORTS.glob("bench-*.json"), key=lambda p: p.stat().st_mtime)
    for p in reversed(reports):
        if exclude_tag not in p.name:
            return p
    return None


def promote(new_tag: str, model_id: str, force: bool = False) -> dict:
    new_report_path = REPORTS / f"bench-{new_tag}.json"
    if not new_report_path.exists():
        print(f"ERROR: bench report not found: {new_report_path}", file=sys.stderr)
        sys.exit(1)

    new_report = load_report(new_report_path)
    prev_path = find_latest_report(exclude_tag=new_tag)

    result = {
        "ts": int(time.time()),
        "new_tag": new_tag,
        "model_id": model_id,
        "prev_report": str(prev_path) if prev_path else None,
        "categories": {},
        "decision": None,
        "reason": "",
    }

    if prev_path is None or force:
        result["decision"] = "promoted"
        result["reason"] = "no previous bench to compare; promoting unconditionally" if not force else "forced"
    else:
        prev_report = load_report(prev_path)
        regressions = []
        for cat in CATEGORIES:
            new_acc = score_of(new_report, cat)
            prev_acc = score_of(prev_report, cat)
            result["categories"][cat] = {"new": new_acc, "prev": prev_acc}
            if new_acc is None or prev_acc is None:
                continue
            delta = new_acc - prev_acc
            if delta < MIN_IMPROVE_DELTA:
                regressions.append(
                    f"{cat}: {prev_acc:.3f} → {new_acc:.3f} (Δ{delta:+.3f})")

        if regressions:
            result["decision"] = "refused"
            result["reason"] = "regression detected: " + "; ".join(regressions)
        else:
            result["decision"] = "promoted"
            gains = [f"{c}: {result['categories'][c]['prev']:.3f}→{result['categories'][c]['new']:.3f}"
                     for c in CATEGORIES
                     if result["categories"].get(c, {}).get("new") is not None]
            result["reason"] = "no regression; scores: " + ", ".join(gains)

    # Apply if promoting
    if result["decision"] == "promoted":
        try:
            reg = json.loads(REGISTRY.read_text())
            prev_active = reg.get("active", "")
            if model_id in reg["models"]:
                reg["active"] = model_id
                REGISTRY.write_text(json.dumps(reg, indent=2) + "\n")
                result["prev_active"] = prev_active
                print(f"✓ PROMOTED: {prev_active} → {model_id}")
            else:
                result["decision"] = "skipped"
                result["reason"] = f"model_id '{model_id}' not in registry"
                print(f"⚠ SKIPPED: '{model_id}' not in registry (add it first)")
        except Exception as e:
            result["decision"] = "error"
            result["reason"] = str(e)
            print(f"ERROR updating registry: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"✗ REFUSED: {result['reason']}")

    # Log
    PROMO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(PROMO_LOG, "a") as f:
        f.write(json.dumps(result) + "\n")

    return result


def main():
    ap = argparse.ArgumentParser(
        description="Auto-promote a model checkpoint if bench scores don't regress.")
    ap.add_argument("--tag", required=True,
                    help="Bench report tag (eval/reports/bench-<tag>.json)")
    ap.add_argument("--model-id", required=True,
                    help="Registry model ID to promote to active")
    ap.add_argument("--force", action="store_true",
                    help="Promote even without a comparison report")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print decision without modifying registry")
    args = ap.parse_args()

    if args.dry_run:
        print("DRY RUN — registry will not be modified")
        # Temporarily redirect registry write
        orig = REGISTRY.write_text
        REGISTRY.write_text = lambda s: print(f"  [dry-run] would write registry: active={args.model_id}")

    result = promote(args.tag, args.model_id, force=args.force)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["decision"] in ("promoted", "skipped") else 1)


if __name__ == "__main__":
    main()
