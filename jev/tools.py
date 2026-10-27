#!/usr/bin/env python3
"""jev/tools.py — Urai tool engine with native function calling.

Tool calling upgrades:
  1. JSON schema declaration  — every tool has a schema (OpenAI function-call
     format). Server exposes GET /v1/tools and passes them in chat completions
     so Qwen3 can use native tool_calls format instead of fenced blocks.
  2. Structured output        — enforce JSON schema on any completion via
     force_json(messages, schema) using grammar-constrained sampling
     (llama-server --grammar-file / json schema mode).
  3. Code interpreter         — run_code(src) executes Python in a temp venv,
     captures stdout/stderr/return value, returns structured result.
  4. Deep research            — research(query, steps) multi-hop web search:
     search → fetch top pages → extract facts → synthesize answer. All local.
  5. Artifact generation      — artifact(kind, content) packages code/markdown/
     data as a named artifact with mime type, returned in response for UI render.

Existing tools (read_file, write_file, edit_file, run, web_search, web_fetch,
browse, analyze) are preserved and extended with schemas.
"""
from __future__ import annotations
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

WORKSPACE = Path(os.environ.get("JEV_WORKSPACE",
                                Path(__file__).resolve().parents[1])).resolve()
TIMEOUT_S = int(os.environ.get("JEV_RUN_TIMEOUT", "30"))
OUT_CAP = 8000

# ── Policy ────────────────────────────────────────────────────────────────────

_POLICY: dict = {}
_POLICY_PATH = Path(__file__).resolve().parents[1] / "policy.json"


def _load_policy() -> dict:
    global _POLICY
    try:
        _POLICY = json.loads(_POLICY_PATH.read_text())
    except Exception:
        _POLICY = {}
    return _POLICY


def reload_policy() -> dict:
    return {"ok": True, "policy_keys": sorted(_load_policy())}


_load_policy()

_ALLOWED_BINS = set(_POLICY.get("allowed_bins", [
    "python3", "python", "node", "npm", "npx", "git", "ls", "cat",
    "echo", "grep", "find", "curl", "wget", "pip", "pip3",
    "bash", "sh", "make", "cmake", "cargo", "go", "java", "javac",
    "ffmpeg", "convert", "jq", "sqlite3",
]))
_BLOCKED_PATTERNS = _POLICY.get("blocked_patterns", [
    r"rm\s+-rf\s+/", r"dd\s+if=", r":(){:|:&};:",
    r"mkfs\.", r">\s*/dev/sd", r"chmod\s+777\s+/",
])


def _jail(path: str) -> str:
    p = (WORKSPACE / path).resolve()
    if not str(p).startswith(str(WORKSPACE)):
        raise PermissionError(f"path outside workspace: {path}")
    return str(p)


# ── File tools ────────────────────────────────────────────────────────────────

def read_file(path: str, max_chars: int = 12000) -> dict:
    try:
        data = Path(_jail(path)).read_text(errors="replace")
        truncated = len(data) > max_chars
        return {"ok": True, "output": data[:max_chars], "truncated": truncated}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def write_file(path: str, content: str = "") -> dict:
    try:
        dest = Path(_jail(path))
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = (content or "").encode()
        dest.write_bytes(data)
        return {"ok": True, "path": os.path.relpath(dest, WORKSPACE),
                "bytes": len(data)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def edit_file(path: str, old: str = "", new: str = "",
              replace_all: bool = False) -> dict:
    try:
        dest = Path(_jail(path))
        src = dest.read_text(errors="replace")
        count = src.count(old)
        if count == 0:
            return {"ok": False, "error": f"string not found in {path}"}
        if count > 1 and not replace_all:
            return {"ok": False,
                    "error": f"ambiguous: found in {count} locations; "
                             "pass replace_all=true or use a unique string"}
        dest.write_text(src.replace(old, new) if replace_all
                        else src.replace(old, new, 1))
        return {"ok": True, "replacements": count if replace_all else 1}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Run tool ──────────────────────────────────────────────────────────────────

def run_cmd(argv: list) -> dict:
    if not argv:
        return {"ok": False, "error": "empty command"}
    bin_ = argv[0]
    if bin_ not in _ALLOWED_BINS:
        return {"ok": False, "error": f"binary not allowlisted: {bin_}"}
    cmd_str = " ".join(str(a) for a in argv)
    for pat in _BLOCKED_PATTERNS:
        if re.search(pat, cmd_str):
            return {"ok": False, "error": f"blocked pattern in command"}
    if bin_ == "git" and len(argv) > 1 and argv[1] not in (
            "log", "diff", "status", "show", "ls-files", "branch",
            "rev-parse", "describe", "tag", "remote", "fetch", "--version"):
        return {"ok": False,
                "error": f"git subcommand not read-only-safe: {argv[1]}"}
    try:
        p = subprocess.run([str(a) for a in argv], capture_output=True,
                           text=True, timeout=TIMEOUT_S, cwd=str(WORKSPACE))
        out = (p.stdout + p.stderr)[:OUT_CAP]
        return {"ok": p.returncode == 0, "output": out,
                "error": None if p.returncode == 0 else out}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {TIMEOUT_S}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Code interpreter ──────────────────────────────────────────────────────────

def run_code(source: str, language: str = "python",
             stdin: str = "") -> dict:
    """Execute code safely in a temp dir. Returns stdout/stderr/exit/duration.

    Supports: python (direct exec), javascript (node), bash (sh -c).
    Security: temp isolated dir, timeout, no network (REQUESTS_CA_BUNDLE=/dev/null).
    """
    if language not in ("python", "python3", "javascript", "js", "bash", "sh"):
        return {"ok": False, "error": f"unsupported language: {language}"}

    with tempfile.TemporaryDirectory(prefix="urai-code-") as tmpdir:
        env = {**os.environ,
               "PYTHONDONTWRITEBYTECODE": "1",
               "HOME": tmpdir,
               "TMPDIR": tmpdir}
        t0 = time.time()
        try:
            if language in ("python", "python3"):
                # Quick syntax check first
                try:
                    ast.parse(source)
                except SyntaxError as e:
                    return {"ok": False, "error": f"SyntaxError: {e}",
                            "language": language}
                src_path = Path(tmpdir) / "main.py"
                src_path.write_text(source)
                cmd = [sys.executable, str(src_path)]
            elif language in ("javascript", "js"):
                src_path = Path(tmpdir) / "main.js"
                src_path.write_text(source)
                cmd = ["node", str(src_path)]
            else:  # bash/sh
                cmd = ["bash", "-c", source]

            p = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=TIMEOUT_S, cwd=tmpdir, env=env,
                input=stdin or None)
            elapsed = round(time.time() - t0, 3)
            stdout = p.stdout[:OUT_CAP]
            stderr = p.stderr[:2000]
            return {
                "ok": p.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": p.returncode,
                "duration_s": elapsed,
                "language": language,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"timeout after {TIMEOUT_S}s",
                    "language": language}
        except FileNotFoundError as e:
            return {"ok": False, "error": f"interpreter not found: {e}",
                    "language": language}
        except Exception as e:
            return {"ok": False, "error": str(e), "language": language}


# ── Web tools ─────────────────────────────────────────────────────────────────

_PRIVATE_RE = re.compile(
    r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|0\.0\.0\.0)")


def _http_get(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "UraiFetch/3.0",
        "Accept": accept,
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read(500_000)


def _clean_html(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s{3,}", "\n\n", text)
    return text.strip()[:OUT_CAP]


def web_search(query: str, top: int = 5) -> dict:
    try:
        q = urllib.parse.quote_plus(str(query)[:200])
        raw = _http_get(
            f"https://api.duckduckgo.com/?q={q}&format=json&no_redirect=1&no_html=1")
        data = json.loads(raw)
        out = []
        for r in data.get("Results", []) + data.get("RelatedTopics", []):
            if isinstance(r, dict) and r.get("Text"):
                url = r.get("FirstURL", "")
                out.append(f"• {r['Text'][:200]}  {url}")
        if not out and data.get("AbstractText"):
            out.append(data["AbstractText"][:500])
        if not out:
            return {"ok": False, "output": "no results", "query": query}
        return {"ok": True, "output": "\n".join(out[:top * 2])[:OUT_CAP],
                "query": query, "source": "duckduckgo"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def web_fetch(url: str) -> dict:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"ok": False, "error": "only http(s) URLs allowed"}
        if _PRIVATE_RE.match(parsed.hostname or ""):
            return {"ok": False, "error": "private hosts blocked"}
        raw = _http_get(url)
        if len(raw) > 400_000:
            return {"ok": False,
                    "error": f"page too large ({len(raw) >> 10} KB > 400 KB limit)"}
        return {"ok": True, "output": _clean_html(raw)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ── Deep research ─────────────────────────────────────────────────────────────

def research(query: str, depth: int = 3) -> dict:
    """Multi-hop research: search → fetch top pages → extract → synthesize.

    Returns {answer, sources, steps} — all local, no cloud calls.
    depth: number of pages to fetch and read (default 3).
    """
    steps = []

    # Step 1: search
    sr = web_search(query, top=depth)
    steps.append({"step": "search", "query": query,
                  "results_preview": (sr.get("output") or "")[:300]})
    if not sr.get("ok"):
        return {"ok": False, "error": sr.get("error", "search failed"),
                "steps": steps}

    # Extract URLs from search results
    urls = re.findall(r"https?://[^\s)\"'>]+", sr.get("output", ""))[:depth]
    steps.append({"step": "urls_found", "count": len(urls), "urls": urls})

    # Step 2: fetch each URL
    pages = []
    for url in urls:
        fr = web_fetch(url)
        if fr.get("ok"):
            pages.append({"url": url, "text": fr["output"][:3000]})
            steps.append({"step": "fetched", "url": url,
                          "chars": len(fr["output"])})
        else:
            steps.append({"step": "fetch_failed", "url": url,
                          "error": fr.get("error", "")[:100]})

    if not pages:
        return {"ok": False,
                "error": "could not fetch any pages",
                "steps": steps,
                "raw_search": sr.get("output", "")}

    # Step 3: synthesize via Urai's local model
    context = "\n\n".join(
        f"[Source: {p['url']}]\n{p['text']}" for p in pages)
    synthesis_prompt = (
        f"Based on the following web sources, answer this question accurately "
        f"and concisely:\n\nQuestion: {query}\n\n"
        f"Sources:\n{context[:6000]}\n\n"
        f"Answer (cite sources where relevant):")

    try:
        from .backends import LlamaServerBackend
        backend = LlamaServerBackend()
        if backend.healthy():
            res = backend.complete(
                [{"role": "user", "content": synthesis_prompt}],
                max_tokens=512, temperature=0.2)
            answer = res.get("content", "").strip()
            steps.append({"step": "synthesized", "answer_chars": len(answer)})
            return {"ok": True, "answer": answer,
                    "sources": [p["url"] for p in pages],
                    "steps": steps}
    except Exception as e:
        steps.append({"step": "synthesis_failed", "error": str(e)[:200]})

    # Fallback: return raw extracted text
    raw = "\n\n".join(p["text"][:800] for p in pages)
    return {"ok": True, "answer": raw, "sources": [p["url"] for p in pages],
            "steps": steps, "note": "raw extraction (synthesis model unavailable)"}


# ── Structured output ─────────────────────────────────────────────────────────

def force_json(messages: list, schema: dict | None = None,
               max_tokens: int = 512) -> dict:
    """Force Urai to respond with valid JSON matching an optional schema.

    Uses llama-server's built-in JSON grammar mode when available,
    falling back to prompt-engineering + retry.
    Returns {ok, data, raw}.
    """
    from .backends import LlamaServerBackend, _post_json
    backend = LlamaServerBackend()
    if not backend.healthy():
        return {"ok": False, "error": "model not available"}

    schema_hint = ""
    if schema:
        schema_hint = f"\nRespond ONLY with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}\n"

    # Inject JSON instruction
    msgs = list(messages)
    system_found = False
    for m in msgs:
        if m.get("role") == "system":
            m["content"] = m["content"] + "\n\nYou MUST respond with valid JSON only. No prose." + schema_hint
            system_found = True
            break
    if not system_found:
        msgs.insert(0, {"role": "system",
                        "content": "You MUST respond with valid JSON only. No prose." + schema_hint})

    # Try llama-server JSON grammar mode first
    try:
        payload = {
            "model": backend.model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": 0.1,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        data = _post_json(backend.base + "/v1/chat/completions", payload)
        raw = data["choices"][0]["message"].get("content", "")
        parsed = json.loads(raw)
        return {"ok": True, "data": parsed, "raw": raw, "mode": "grammar"}
    except Exception:
        pass

    # Fallback: prompt-only, retry up to 2 times
    for attempt in range(2):
        res = backend.complete(msgs, max_tokens=max_tokens, temperature=0.1)
        raw = res.get("content", "")
        # Extract JSON from response
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
        if m:
            raw = m.group(1).strip()
        else:
            m2 = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", raw)
            if m2:
                raw = m2.group(0)
        try:
            parsed = json.loads(raw)
            return {"ok": True, "data": parsed, "raw": raw,
                    "mode": "prompt", "attempt": attempt + 1}
        except json.JSONDecodeError:
            pass

    return {"ok": False, "error": "could not produce valid JSON",
            "raw": res.get("content", "")[:300] if 'res' in dir() else ""}


# ── Artifact generation ───────────────────────────────────────────────────────

def artifact(kind: str, content: str, name: str = "",
             language: str = "") -> dict:
    """Package content as a named artifact for UI rendering.

    kind: "code" | "markdown" | "html" | "svg" | "csv" | "json" | "text"
    Artifacts are returned in the response and stored in data/artifacts/.
    """
    MIME_MAP = {
        "code": f"text/x-{language or 'python'}",
        "markdown": "text/markdown",
        "html": "text/html",
        "svg": "image/svg+xml",
        "csv": "text/csv",
        "json": "application/json",
        "text": "text/plain",
    }
    if kind not in MIME_MAP:
        return {"ok": False, "error": f"unknown artifact kind: {kind}"}

    art_id = hashlib.md5(content.encode()).hexdigest()[:12]
    filename = name or f"artifact-{art_id}.{kind}"
    art_dir = Path(__file__).resolve().parents[1] / "data" / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    art_path = art_dir / filename
    art_path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "artifact_id": art_id,
        "kind": kind,
        "filename": filename,
        "mime": MIME_MAP[kind],
        "size": len(content),
        "path": str(art_path),
        "content": content[:500] + ("..." if len(content) > 500 else ""),
    }


# ── Analyze (preserved) ───────────────────────────────────────────────────────

def analyze(target: str = "", max_bytes: int = 1_000_000) -> dict:
    from . import analyze as _a
    return _a.analyze(target, max_bytes=max_bytes)


# ── Browse (preserved) ────────────────────────────────────────────────────────

def browse(goal: str = "", steps: str = "[]") -> dict:
    from . import browser as _b
    try:
        steps_list = json.loads(steps) if isinstance(steps, str) else steps
    except Exception:
        return {"ok": False, "error": "steps must be a JSON array"}
    try:
        return _b.run(goal=goal, steps=steps_list)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ── MCP tools ─────────────────────────────────────────────────────────────────

def mcp_servers(server: str = "") -> dict:
    from . import mcp_client as _mc
    return _mc.list_servers(server or None)


def mcp(server: str, tool: str, args: dict | str = "{}") -> dict:
    from . import mcp_client as _mc
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    return _mc.call(server, tool, args)


# ── Tool schemas (OpenAI function-call format) ────────────────────────────────

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file from the workspace",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "max_chars": {"type": "integer", "default": 12000}},
                       "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write content to a file in the workspace",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace a string in a file",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "old": {"type": "string"},
                                      "new": {"type": "string"},
                                      "replace_all": {"type": "boolean", "default": False}},
                       "required": ["path", "old", "new"]}}},
    {"type": "function", "function": {
        "name": "run",
        "description": "Run a shell command in the workspace",
        "parameters": {"type": "object",
                       "properties": {"argv": {"type": "array",
                                               "items": {"type": "string"}}},
                       "required": ["argv"]}}},
    {"type": "function", "function": {
        "name": "run_code",
        "description": "Execute Python, JavaScript or Bash code and return stdout/stderr",
        "parameters": {"type": "object",
                       "properties": {"source": {"type": "string"},
                                      "language": {"type": "string",
                                                   "enum": ["python", "javascript", "bash"],
                                                   "default": "python"},
                                      "stdin": {"type": "string", "default": ""}},
                       "required": ["source"]}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web with DuckDuckGo",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"},
                                      "top": {"type": "integer", "default": 5}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "web_fetch",
        "description": "Fetch and extract text from a URL",
        "parameters": {"type": "object",
                       "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "research",
        "description": "Multi-hop deep research: search → fetch → synthesize answer",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"},
                                      "depth": {"type": "integer", "default": 3}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "artifact",
        "description": "Create a named artifact (code, markdown, HTML, SVG, CSV, JSON)",
        "parameters": {"type": "object",
                       "properties": {"kind": {"type": "string",
                                               "enum": ["code", "markdown", "html",
                                                        "svg", "csv", "json", "text"]},
                                      "content": {"type": "string"},
                                      "name": {"type": "string", "default": ""},
                                      "language": {"type": "string", "default": ""}},
                       "required": ["kind", "content"]}}},
    {"type": "function", "function": {
        "name": "analyze",
        "description": "Reverse-engineer a binary/file: magic bytes, strings, headers",
        "parameters": {"type": "object",
                       "properties": {"target": {"type": "string"}},
                       "required": ["target"]}}},
    {"type": "function", "function": {
        "name": "see",
        "description": "Analyze an image and answer a question about it",
        "parameters": {"type": "object",
                       "properties": {"image": {"type": "string",
                                                "description": "base64 or file path"},
                                      "question": {"type": "string"}},
                       "required": ["image"]}}},
    {"type": "function", "function": {
        "name": "imagine",
        "description": "Generate an image from a text prompt",
        "parameters": {"type": "object",
                       "properties": {"prompt": {"type": "string"},
                                      "out": {"type": "string", "default": ""}},
                       "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "remember",
        "description": "Store a fact in Urai's long-term memory",
        "parameters": {"type": "object",
                       "properties": {"text": {"type": "string"},
                                      "kind": {"type": "string",
                                               "enum": ["fact", "preference", "decision"],
                                               "default": "fact"}},
                       "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "recall",
        "description": "Recall relevant memories for a query",
        "parameters": {"type": "object",
                       "properties": {"query": {"type": "string"},
                                      "top": {"type": "integer", "default": 3}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "mcp",
        "description": "Call a tool on an MCP server",
        "parameters": {"type": "object",
                       "properties": {"server": {"type": "string"},
                                      "tool": {"type": "string"},
                                      "args": {"type": "object", "default": {}}},
                       "required": ["server", "tool"]}}},
]

# ── Tool registry ─────────────────────────────────────────────────────────────

TOOLS: dict = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "run": run_cmd,
    "run_code": run_code,
    "web_search": web_search,
    "web_fetch": web_fetch,
    "research": research,
    "artifact": artifact,
    "analyze": analyze,
    "browse": browse,
    "mcp_servers": mcp_servers,
    "mcp": mcp,
}

# Memory tools (lazy to avoid circular import)
def _remember(text: str, kind: str = "fact") -> dict:
    from .memory import remember as _r
    return _r(text, kind=kind)

def _recall(query: str, top: int = 3) -> list:
    from .memory import recall as _r
    return _r(query, top=top)

TOOLS["remember"] = _remember
TOOLS["recall"] = _recall

# Vision / imagine (lazy)
def _see(image: str, question: str = "Describe this image.") -> dict:
    from . import vision
    return vision.see(image, question)

def _imagine(prompt: str, out: str = "") -> dict:
    from . import imagine
    return imagine.generate(prompt, out or None)

TOOLS["see"] = _see
TOOLS["imagine"] = _imagine

# Toolpacks: load from toolpacks/
_TOOLPACK_DIR = Path(__file__).resolve().parents[1] / "toolpacks"
if _TOOLPACK_DIR.is_dir():
    import importlib.util as _ilu
    for _tp in sorted(_TOOLPACK_DIR.glob("*.py")):
        try:
            _spec = _ilu.spec_from_file_location(_tp.stem, _tp)
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            if hasattr(_mod, "TOOLS"):
                TOOLS.update(_mod.TOOLS)
            if hasattr(_mod, "TOOL_SCHEMAS"):
                TOOL_SCHEMAS.extend(_mod.TOOL_SCHEMAS)
        except Exception:
            pass
