#!/usr/bin/env python3
"""Harness benchmark: deterministic capability checks + optional live runs.

Quick (default, no LLM): tool jail/roundtrips, toolpacks, MCP loop,
plan interception, brand map, registry sanity.
Full (--full): + plan-mode agent + conductor smoke (several CPU minutes).

Run: python3 jev/bench_harness.py --tag local [--full]
  => eval/reports/bench-harness-<tag>.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "eval" / "reports"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="local")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    out = {"tag": args.tag, "full": args.full,
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "identity": "Urai, developed by Tynio LTD",
           "checks": {}, "calls": 0}
    t0 = time.time()

    def check(name, ok, detail=""):
        out["checks"][name] = {"pass": bool(ok), "detail": str(detail)[:200]}
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {str(detail)[:80]}", flush=True)

    import os
    os.environ.setdefault("JEV_WORKSPACE", "/tmp")
    from jev import tools as T
    from jev.brand import brand_id, brand_list, tier_of_brand

    # T1 write->read roundtrip
    r = T.TOOLS["write_file"]("urai-hbench.txt", "HARNESS-OK-123")
    r2 = T.TOOLS["read_file"]("urai-hbench.txt")
    check("tool-write-read", r.get("ok") and r2.get("output") == "HARNESS-OK-123")
    # T2 ambiguous edit refused
    T.TOOLS["write_file"]("urai-hbench2.txt", "aa bb aa")
    r = T.TOOLS["edit_file"]("urai-hbench2.txt", "aa", "zz")
    check("tool-edit-unique", (not r.get("ok")) and "2 locations" in r.get("error", ""))
    # T3 jail escape refused
    r = T.TOOLS["read_file"]("../../etc/passwd")
    check("tool-jail", not r.get("ok"))
    # T4 toolpack present
    names = [n for n in T.TOOLS if not n.startswith("_")]
    check("toolpacks", "repo-log" in names, len(names))
    # T5 MCP self-loop (spawns local server; no network)
    try:
        m = T.TOOLS["mcp_servers"]("")
        ok = "urai-local" in json.dumps(m)
    except Exception as e:
        ok, m = False, str(e)[:100]
    check("mcp-loop", ok)
    # T6 brand map covers internals, no raw qwen in brands
    ids = [b["id"] for b in brand_list()]
    check("brands", set(ids) == {"urai", "urai-fast", "urai-ultra", "urai-cyber", "laya", "cyberurai-v1"}
          and brand_id("qwen3-4B-Q4_K_M") == "urai"
          and tier_of_brand("laya") == "urai-ultra", ids)
    # T7 registry sanity: active chat model file exists
    from jev import models_registry as R
    reg = R.load()
    mid, m = R.active_model(reg)
    check("registry-active", (ROOT / m["path"]).exists(), f"{mid} {m.get('params')}")
    # T8 plan interception (no LLM)
    from jev.agent import run_tool_call
    r = run_tool_call({"tool": "write_file", "args": {"path": "x", "content": "y"}}, plan=True)
    check("plan-intercept", r.get("plan_only") is True)
    # cleanup
    for f in ("urai-hbench.txt", "urai-hbench2.txt"):
        try:
            (Path("/tmp") / f).unlink()
        except Exception:
            pass

    if args.full:
        from jev import conductor as C
        c = C.run_conductor("Reply with the word CONDUCTOR-OK after one verification step.",
                            {}, 256, 2)
        check("conductor-live", c.get("ok") is True, str(c.get("subtasks"))[:60])

    out["total_s"] = round(time.time() - t0, 1)
    passed = sum(1 for v in out["checks"].values() if v["pass"])
    out["passed"] = passed
    out["total"] = len(out["checks"])
    REPORTS.mkdir(parents=True, exist_ok=True)
    fp = REPORTS / f"bench-harness-{args.tag}.json"
    fp.write_text(json.dumps(out, indent=2))
    print(f"\nHARNESS-BENCH {args.tag}: {passed}/{len(out['checks'])} total_s={out['total_s']}")
    print(f"report: {fp}")


if __name__ == "__main__":
    main()
