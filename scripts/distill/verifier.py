#!/usr/bin/env python3
"""Verifier-first scoring for distillation candidates (mission §8).

Every teacher output is scored BEFORE it can enter the dataset:

  code blocks  -> python compile check (py_compile), per-block
  json blocks   -> strict json.loads
  whole text    -> secret scan (keys, passwords, tokens, private paths)
                -> banned-pattern scan (eval(, fabricated claims...)

Result: score 0.0..1.0 + list of failure tags. Only score >= threshold
(default 0.8) passes to the dataset. A mediocre answer that compiles and
contains no secrets beats a beautiful one that does not.
"""

import ast
import io
import json
import re
import tokenize

SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[\w\-]{8,}", "leaked-api-key"),
    (r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{4,}", "leaked-password"),
    (r"(?i)bearer\s+[A-Za-z0-9_\-\.~\+/]+=*", "leaked-bearer-token"),
    (r"(?i)(secret|token)\s*[:=]\s*['\"]?[\w\-]{8,}", "leaked-secret"),
    (r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----", "leaked-private-key"),
    (r"/home/[\w\-]+", "private-home-path"),
    (r"(?i)sk-(test|live)-[A-Za-z0-9]+", "leaked-sk-key"),
]

BANNED_PATTERNS = [
    (r"\beval\s*\(", "unsafe-eval"),
    (r"benchmark.{0,40}\d+x faster", "fabricated-benchmark"),
    (r"(?i)as an ai language model", "model-slop"),
]

FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def extract_blocks(text):
    return [(lang.lower() or "text", body) for lang, body in FENCE_RE.findall(text)]


def check_python(code: str):
    try:
        compile(code, "<candidate>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"syntax-error: {e}"


def check_json(code: str):
    try:
        json.loads(code)
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"json-error: {e}"


def verify(content: str, exec_python: bool = False) -> dict:
    failures = []
    checks = 0
    passed = 0
    exec_results = []

    for lang, body in extract_blocks(content):
        if lang == "python":
            checks += 1
            ok, msg = check_python(body)
            if ok:
                if exec_python:
                    from exec_check import run_block
                    res = run_block(body)
                    exec_results.append(res)
                    if res["passed"]:
                        passed += 1
                    else:
                        failures.append("exec-fail: " + (res["error"] or "unknown")[:200])
                else:
                    passed += 1
            else:
                failures.append(msg)
        elif lang == "json":
            checks += 1
            ok, msg = check_json(body)
            if ok:
                passed += 1
            else:
                failures.append(msg)

    for pattern, tag in SECRET_PATTERNS + BANNED_PATTERNS:
        if re.search(pattern, content):
            failures.append(tag)

    if checks == 0:
        # No executable artifacts to verify: neutral, not trusted.
        score = 0.5 if not failures else 0.0
    else:
        score = passed / checks
        if failures and passed == checks:
            score = max(0.0, score - 0.5)  # secrets/slop sink verified code

    # Hard fail on any leak-class tag regardless of code correctness.
    leak_tags = {"leaked-api-key", "leaked-password", "leaked-bearer-token",
                 "leaked-secret", "leaked-private-key", "private-home-path",
                 "leaked-sk-key"}
    if leak_tags.intersection(failures):
        score = 0.0

    return {"score": round(score, 3), "checks": checks,
            "passed": passed, "failures": failures,
            "exec": exec_results}
