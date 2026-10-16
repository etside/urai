#!/usr/bin/env python3
"""Urai API integration test — stdlib only, no real model required.

Runs against an API already listening on URAI_BASE (default
http://127.0.0.1:8771). The CI job starts it deterministically with:

    URAI_API_KEY=testkey \
    URAI_FORCE_MOCK=1 \
    URAI_AUTH_GET=1 \
    URAI_PORT=8771 \
    JEV_LLAMA_URL=http://127.0.0.1:9 \
    python3 -m jev.server

Server-side contract this test depends on (see jev/server.py, jev/router.py,
jev/backends.py — owned by another engineer, noted in the PR report):

  1. ``URAI_FORCE_MOCK`` (or "llama is down") makes the router hand chat
     requests to ``backends.MockBackend`` instead of returning 502. Without a
     model the whole test must still be deterministic.
  2. ``/v1/chat/completions`` responses carry ``urai.nlp`` (``nlp.analyze``)
     and ``urai.vibe`` (``vibe.plan``) metadata.
  3. ``URAI_AUTH_GET=1`` applies the API-key gate to GET discovery routes
     (``/v1/benchmarks``), keeping ``/health`` and ``/v1/models`` public.
  4. Every response carries an ``X-Request-Id`` header.

Asserts:
  a) GET /v1/models -> exactly ["urai", "cyberurai"]
  b) unauth POST /v1/chat/completions -> 401 + one error contract
  c) auth POST -> chat.completion with urai.nlp + urai.vibe
  d) stream -> multiple ``data:`` chunks then ``[DONE]``
  e) X-Request-Id present
  f) GET /v1/benchmarks -> 401 without key, 200 with key
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("URAI_BASE", "http://127.0.0.1:8771").rstrip("/")
KEY = os.environ.get("URAI_API_KEY", "testkey")

FAIL = []


def check(name, cond, extra=""):
    line = ("PASS " if cond else "FAIL ") + name
    if extra and not cond:
        line += " — " + extra
    print(line)
    if not cond:
        FAIL.append(name)


def _hget(headers, name):
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return ""


def req(method, path, body=None, key=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "X-Device-Id": "ci-probe"}
    if key:
        headers["Authorization"] = "Bearer " + key
    r = urllib.request.Request(BASE + path, data=data, headers=headers,
                               method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=timeout)
        return resp.getcode(), dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def wait_health(timeout=30):
    for _ in range(timeout):
        try:
            code, _, _ = req("GET", "/health", timeout=2)
            if code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def main():
    if not wait_health():
        sys.exit(f"API at {BASE} never became healthy")

    # (a) public model list is exactly the two brands ----------------------
    code, headers, body = req("GET", "/v1/models")
    doc = json.loads(body or b"{}")
    ids = [m.get("id") for m in doc.get("data", [])]
    check("a) GET /v1/models ids == [urai, cyberurai]", code == 200
          and ids == ["urai", "cyberurai"], f"code={code} ids={ids}")

    # (e) request-id header on a normal response ---------------------------
    rid = _hget(headers, "X-Request-Id")
    check("e) response has X-Request-Id", bool(rid), str(headers))

    # (b) unauthenticated POST is rejected with the one error contract -----
    code, _, body = req("POST", "/v1/chat/completions",
                        {"messages": [{"role": "user", "content": "hi"}],
                         "max_tokens": 16})
    err = json.loads(body or b"{}")
    e = err.get("error", {})
    check("b) unauth POST -> 401", code == 401, f"code={code} body={body[:160]!r}")
    check("b) error contract {message,type,code:invalid_api_key}",
          isinstance(e, dict) and e.get("code") == "invalid_api_key"
          and isinstance(e.get("message"), str) and isinstance(e.get("type"), str),
          str(err)[:200])

    # (c) authenticated POST -> chat.completion with nlp + vibe ------------
    code, _, body = req("POST", "/v1/chat/completions",
                        {"messages": [{"role": "user",
                                       "content": "hello there, how are you?"}],
                         "max_tokens": 32}, key=KEY)
    doc = json.loads(body or b"{}")
    urai = doc.get("urai", {}) if isinstance(doc, dict) else {}
    check("c) auth POST -> chat.completion",
          code == 200 and doc.get("object") == "chat.completion"
          and bool(doc.get("choices")), f"code={code} body={body[:200]!r}")
    check("c) response carries urai.nlp", "nlp" in urai,
          str(urai)[:200])
    check("c) response carries urai.vibe", "vibe" in urai,
          str(urai)[:200])

    # (d) streaming: many data: chunks then [DONE] -------------------------
    data = json.dumps({"messages": [{"role": "user",
                                     "content": "stream this please"}],
                       "max_tokens": 64, "stream": True}).encode()
    r = urllib.request.Request(
        BASE + "/v1/chat/completions", data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY, "X-Device-Id": "ci-probe"})
    chunks = []
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            for line in resp:
                line = line.decode().strip()
                if line.startswith("data:"):
                    chunks.append(line[5:].strip())
    except Exception as ex:
        check("d) stream request ok", False, str(ex))
    check("d) stream ends with [DONE]", bool(chunks) and chunks[-1] == "[DONE]",
          str(chunks[-1:]))
    check("d) stream has multiple data: chunks", len(chunks) >= 2,
          f"chunks={len(chunks)} (needs token-level SSE; see server assumptions)")

    # (f) GET auth gate on a protected discovery route ---------------------
    code0, _, _ = req("GET", "/v1/benchmarks")
    check("f) GET /v1/benchmarks without key -> 401", code0 == 401, f"code={code0}")
    code1, _, body1 = req("GET", "/v1/benchmarks", key=KEY)
    check("f) GET /v1/benchmarks with key -> 200", code1 == 200,
          f"code={code1} body={body1[:160]!r}")

    # (g) one error contract on a flat 404 ---------------------------------
    code, _, body = req("POST", "/v1/no-such-route", {"x": 1}, key=KEY)
    e = json.loads(body or b"{}").get("error", {})
    check("g) flat error normalized to {message,type,code:not_found}",
          code == 404 and isinstance(e, dict) and e.get("code") == "not_found"
          and isinstance(e.get("message"), str) and isinstance(e.get("type"), str),
          f"code={code} body={body[:200]!r}")

    # (h) admin metrics is master-gated + returns cache/request counters ---
    master = os.environ.get("URAI_MASTER_KEY", "856777")
    code0, _, _ = req("GET", "/admin/metrics")
    check("h) GET /admin/metrics without key -> 403", code0 == 403, f"code={code0}")
    code1, _, body1 = req("GET", "/admin/metrics?key=" + master)
    doc = json.loads(body1 or b"{}")
    check("h) GET /admin/metrics with key -> 200 + cache + requests",
          code1 == 200 and "cache" in doc and "requests" in doc
          and "uptime_seconds" in doc, f"code={code1} body={body1[:200]!r}")

    # (i) Prometheus text exposition ---------------------------------------
    code, _, body = req("GET", "/metrics")
    text = (body or b"").decode("utf-8", "replace")
    check("i) GET /metrics -> Prometheus text",
          code == 200 and "urai_uptime_seconds" in text
          and "urai_cache_hits_total" in text, f"code={code} body={text[:160]!r}")

    # (j) admin cache clear (master-gated) ---------------------------------
    code, _, body = req("POST", "/admin/cache/clear", {"master_key": master})
    doc = json.loads(body or b"{}")
    check("j) POST /admin/cache/clear -> ok",
          code == 200 and doc.get("ok") is True, f"code={code} body={body[:160]!r}")

    # (k) /trace UI page renders -------------------------------------------
    code, _, body = req("GET", "/trace")
    check("k) GET /trace -> html", code == 200 and b"<html" in body.lower(),
          f"code={code}")

    print(f"\n{len(FAIL)} failure(s)" if FAIL else "\nall API checks passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
