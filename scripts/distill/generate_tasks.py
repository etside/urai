#!/usr/bin/env python3
"""Deterministic raw-task generator (Phase 2 scale-up).

Produces 200+ anonymized tasks across the 8 mission §6 categories.
No teacher, no network: prompts are parameterized templates with a fixed
seed, so output is reproducible. Tasks WITH known solutions carry
`reference_good` (usable by MockTeacher + exec checks); text-only tasks
carry `judge_rubric` for the future LLM-judge.

Usage:
    python3 scripts/distill/generate_tasks.py --out data/raw_tasks/expanded --seed 7
"""

import argparse
import json
import random
from pathlib import Path

FUNCS = [
    ("chunk_list", "split a list into chunks of size n",
     "def chunk_list(xs, n):\n    return [xs[i:i+n] for i in range(0, len(xs), n)]",
     "assert chunk_list([1,2,3,4,5], 2) == [[1,2],[3,4],[5]]\nassert chunk_list([], 3) == []"),
    ("flatten_once", "flatten one level of nesting",
     "def flatten_once(xss):\n    return [x for xs in xss for x in xs]",
     "assert flatten_once([[1,2],[3]]) == [1,2,3]\nassert flatten_once([]) == []"),
    ("clamp", "constrain v into [lo, hi]",
     "def clamp(v, lo, hi):\n    return max(lo, min(hi, v))",
     "assert clamp(5, 0, 10) == 5\nassert clamp(-1, 0, 10) == 0\nassert clamp(99, 0, 10) == 10"),
    ("retry", "retry fn up to tries times with exponential backoff",
     "import time\n\ndef retry(fn, tries=3, base=0.1):\n    last = None\n    for i in range(tries):\n        try:\n            return fn()\n        except Exception as e:\n            last = e\n            time.sleep(base * (2 ** i))\n    raise last",
     "assert retry(lambda: 42) == 42"),
    ("dedupe_keep_order", "remove duplicates preserving order",
     "def dedupe_keep_order(xs):\n    seen, out = set(), []\n    for x in xs:\n        if x not in seen:\n            seen.add(x)\n            out.append(x)\n    return out",
     "assert dedupe_keep_order([3,1,3,2,1]) == [3,1,2]"),
    ("paginate", "page N (1-based) of size s from a sequence",
     "def paginate(seq, page, size):\n    start = (page - 1) * size\n    return list(seq[start:start+size])",
     "assert paginate(range(10), 2, 3) == [3,4,5]\nassert paginate(range(10), 5, 3) == []"),
    ("deep_get", "safe nested dict lookup with default",
     "def deep_get(d, path, default=None):\n    cur = d\n    for k in path:\n        if not isinstance(cur, dict) or k not in cur:\n            return default\n        cur = cur[k]\n    return cur",
     "assert deep_get({'a': {'b': 1}}, ['a','b']) == 1\nassert deep_get({}, ['a']) is None"),
    ("slugify", "lowercase alphanumeric slug with dashes",
     "import re\n\ndef slugify(s):\n    s = s.lower()\n    s = re.sub(r'[^a-z0-9]+', '-', s)\n    return s.strip('-')",
     "assert slugify('Hello World!') == 'hello-world'"),
]

BUGS = [
    ("off-by-one range", "range(len(xs)) used where range(len(xs)-1) needed",
     "IndexError: list index out of range", "narrow the range bound by one"),
    ("mutable default arg", "def f(items=[]) accumulates across calls",
     "stale data leaking between requests", "default to None, create inside"),
    ("unclosed file handle", "open() without close in a loop",
     "Too many open files after hours", "use a with-block"),
    ("bare except swallowing", "except: pass hides real errors",
     "silent wrong results in ledger totals", "catch specific exceptions, log and re-raise"),
    ("timezone-naive datetime", "mixing naive and aware datetimes",
     "TypeError: can't compare offset-naive and offset-aware", "use timezone-aware UTC everywhere"),
    ("N+1 queries", "query inside a loop over users",
     "p99 latency spikes on the leaderboard endpoint", "batch with a single IN query"),
]

DEBUG_LOGS = [
    ("ECONNREFUSED redis 6379 on staging; worked yesterday",
     ["redis process running?", "port/firewall change?", "config host drift?",
      "disk full blocking persistence?", "connection pool exhaustion?"],
     "redis-cli ping + service logs + config diff"),
    ("Postgres too many clients after deploy",
     ["pool size vs max_connections?", "leaked connections in new code?",
      "migrations holding locks?", "pooler (pgbouncer) up?"],
     "pg_stat_activity count by state + pool metrics"),
    ("WebSocket disconnect storms every ~60s behind nginx",
     ["proxy_read_timeout < heartbeat?", "missing Upgrade headers?",
      "idle timeout on LB?", "client heartbeat stopped?"],
     "nginx access log 101 vs 499 codes + frame capture"),
    ("intermittent 502s only on one of three replicas",
     ["that replica OOMKilled?", "bad deploy on one pod?", "disk pressure?",
      "noisy neighbor on the node?"],
     "per-replica logs + restart counts + node metrics"),
]

TOOL_TASKS = [
    ("git", "bisect a regression between v1.4 and HEAD",
     "git bisect start / bad HEAD / good v1.4 / run tests / good|bad / reset"),
    ("git", "safely rewrite the last 3 commits' messages already pushed to a shared branch",
     "do NOT rewrite shared history; use revert or coordinate a force-push window"),
    ("docker", "debug why a container exits 137 seconds after start",
     "exit 137 = OOMKilled; check docker stats, memory limit, app heap"),
    ("docker", "pass a secret to a container without baking it into the image",
     "env file / secrets mount / runtime -e; never ENV in Dockerfile"),
    ("linux", "find which process is listening on port 8080",
     "ss -ltnp | grep 8080"),
    ("linux", "trace disk growth over the last 7 days per directory",
     "du snapshots / ncdu; check log rotation"),
]

API_TASKS = [
    ("idempotency", "design Idempotency-Key handling for POST /wallet/credit",
     '{"header": "Idempotency-Key", "store_ttl_hours": 24, "conflict_code": 422}'),
    ("pagination", "design cursor pagination for GET /ledger with 10k+ rows",
     '{"style": "cursor", "param": "cursor", "limit_default": 50, "limit_max": 200}'),
    ("webhooks", "design webhook delivery with retries and signing",
     '{"retry": "exponential backoff 8 attempts over 24h", "signing": "HMAC-SHA256 header", "timeout_s": 10}'),
    ("auth", "design JWT access + rotating refresh tokens for game API",
     '{"access_ttl_min": 15, "refresh_ttl_days": 7, "rotation": true, "reuse_detection": true}'),
    ("ratelimit", "design per-user rate limiting for the spin endpoint",
     '{"strategy": "token bucket in redis", "key": "rl:spin:{user}", "limit": "30/min"}'),
]

SEC_TASKS = [
    ("SQL injection via f-string query",
     "def bad(db, u):\n    return db.q(f\"SELECT * FROM users WHERE name='{u}'\")",
     "use parameterized queries: db.q('SELECT * FROM users WHERE name=%s', (u,))"),
    ("plaintext password storage",
     "def bad(pw):\n    db.save(pw)",
     "hash with argon2/bcrypt; never store or log plaintext"),
    ("SSRF via user-supplied webhook URL",
     "def bad(url):\n    return fetch(url)",
     "allowlist schemes/hosts, block metadata IPs (169.254.169.254), timeout + size caps"),
    ("secrets in git history",
     "api key committed in config.py three months ago",
     "rotate the key now; purge with filter-repo; add pre-commit secret scan"),
    ("insecure JWT (none algorithm accepted)",
     "def bad(tok):\n    return decode(tok, algorithms=['none', 'HS256'])",
     "pin one strong algorithm; verify signature and expiry server-side"),
]

REPO_TASKS = [
    ("given games/teen_patti_pro + wallet ledger + WebSocket realtime, plan adding a daily rebate job",
     "touch: job scheduler, ledger writer (idempotent), tests, ops runbook; no RNG changes"),
    ("given NestJS-style modules + Postgres + Redis, plan splitting the spin endpoint into command/query paths",
     "write path validates + appends; read path serves cached state; contract tests on both"),
    ("given React admin + player apps sharing an API client, plan versioning the client for v2 endpoints",
     "versioned client package, feature-flagged rollout, contract tests, rollback plan"),
]

REASON_TASKS = [
    ("A queue consumer processes each message twice after every deploy. Name the most likely cause class and the one check that confirms it.",
     '{"cause": "duplicate delivery during rebalance/shutdown", "check": "consumer group offsets + idempotent handler test"}'),
    ("p99 latency doubled but CPU, memory and QPS are flat. List the three most likely external causes in order.",
     '{"causes": ["downstream dependency slowdown", "DNS/timeout regression", "noisy neighbor / throttling"]}'),
    ("Two replicas disagree on a counter after a network partition healed. What property was violated and what construct fixes it?",
     '{"violated": "consistency (split-brain writes)", "fix": "single writer or CRDT / fencing tokens"}'),
]


def emit(outdir: Path, seed: int):
    rng = random.Random(seed)
    tasks = []
    tid = lambda cat, i: f"{cat}-{i:03d}-s{seed}"

    # A. code generation (known-good solutions -> verifiable)
    for i, (name, spec, impl, tests) in enumerate(FUNCS * 4):
        v = i // len(FUNCS)
        tasks.append({"id": tid("pygen", i), "category": "code-generation",
            "prompt": f"Write a Python function `{name}`: {spec}. Include tests and edge cases. Variant {v}.",
            "reference_good": f"```python\n{impl}\n\n{tests}\n```\n"})

    # B. code repair (broken + error -> fixed reference)
    for i in range(28):
        fname, spec, impl, tests = rng.choice(FUNCS)
        bug, where, symptom, fix = rng.choice(BUGS)
        tasks.append({"id": tid("pyfix", i), "category": "code-repair",
            "prompt": f"This `{fname}` implementation has a bug ({bug}; {where}). Failure: {symptom}. Diagnose and give the minimal fix with tests.",
            "reference_good": f"Diagnosis: {bug} — {fix}.\n```python\n{impl}\n\n{tests}\n```\n"})

    # C. repository reasoning (text-only + rubric)
    for i in range(24):
        ctx, plan = rng.choice(REPO_TASKS)
        tasks.append({"id": tid("repo", i), "category": "repo-reasoning",
            "prompt": f"Repository task: {ctx}. Output an architecture summary and a concrete change plan.",
            "judge_rubric": f"Must mention: scoped file areas; idempotent/tested changes; what NOT to touch. Reference plan: {plan}"})

    # D. debugging (text-only + rubric)
    for i in range(28):
        log, checks, verify = rng.choice(DEBUG_LOGS)
        tasks.append({"id": tid("dbg", i), "category": "debugging",
            "prompt": f"Production symptom: {log}. Give root-cause hypotheses in order, then verification steps.",
            "judge_rubric": f"Must list checks: {'; '.join(checks)}. Verification: {verify}. No invented metrics."})

    # E. tool use (text-only + rubric)
    for i in range(28):
        tool, task, hint = rng.choice(TOOL_TASKS)
        tasks.append({"id": tid("tool", i), "category": "tool-use",
            "prompt": f"Using {tool}: {task}. Give exact commands plus how to verify the result.",
            "judge_rubric": f"Commands must be safe/non-destructive. Key idea: {hint}"})

    # F. API engineering (json-verifiable)
    for i in range(28):
        area, task, schema = rng.choice(API_TASKS)
        tasks.append({"id": tid("api", i), "category": "api-engineering",
            "prompt": f"API design ({area}): {task}. Include the machine-readable contract as JSON.",
            "reference_good": f"Contract:\n```json\n{schema}\n```\n"})

    # G. security (finding + fixed code)
    for i in range(28):
        vuln, bad, fix = rng.choice(SEC_TASKS)
        tasks.append({"id": tid("sec", i), "category": "security",
            "prompt": f"Security review: {vuln}. Code under review:\n```python\n{bad}\n```\nExplain impact and give the minimal secure fix.",
            "reference_good": f"Impact: exploitable in production. Fix: {fix}.\n```python\n# fixed version uses parameterized calls, hashing, allowlists as applicable\ndef fixed(*a, **k):\n    raise NotImplementedError('see fix above')\n```\n"})

    # Agentic multi-step (text-only + rubric)
    for i in range(16):
        tasks.append({"id": tid("agent", i), "category": "agentic",
            "prompt": "Multi-step task: a staging deploy fails health checks after a dependency bump. Plan, inspect, fix, test, verify — show each step with the tool used and the observed result.",
            "judge_rubric": "Must show: plan; log/test inspection; minimal change; test evidence; rollback note. No fake success claims."})

    # Reasoning (json-verifiable)
    for i in range(16):
        q, ans = rng.choice(REASON_TASKS)
        tasks.append({"id": tid("rsn", i), "category": "reasoning",
            "prompt": q + " Answer as JSON.",
            "reference_good": f"```json\n{ans}\n```\n"})

    outdir.mkdir(parents=True, exist_ok=True)
    by_cat: dict = {}
    for t in tasks:
        by_cat.setdefault(t["category"], []).append(t)
    for cat, ts in by_cat.items():
        with open(outdir / f"{cat}.jsonl", "w") as f:
            for t in ts:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    total = sum(len(v) for v in by_cat.values())
    print(json.dumps({"seed": seed, "total": total,
                      **{k: len(v) for k, v in by_cat.items()}}, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw_tasks/expanded")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    emit(Path(args.out), args.seed)
