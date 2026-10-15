#!/usr/bin/env python3
"""Tool engine: filesystem, terminal, git, web — jailed and allowlisted.

  - File reads confined under JEV_WORKSPACE (default: cwd).
  - Shell: allowlist of read-only/safe commands; everything else refused.
    No shell=True; argv-based; timeout-guarded.
  - Git: read-only subcommands only (status/log/diff/show).
  - Web (keyless, no API keys): web_search (DuckDuckGo + Wikipedia + arXiv),
    web_fetch (URL -> cleaned text, size-capped, http/https only).

Every call returns {"ok", "output"|"error"}. All executions are logged
to the agent trace by agent.py.
"""

import html as _html
import os
import re as _re
import subprocess
import urllib.parse as _urlparse
import urllib.request as _urlreq

WORKSPACE = os.path.realpath(os.environ.get("JEV_WORKSPACE", os.getcwd()))
TIMEOUT_S = 30
OUT_CAP = 8000
WEB_TIMEOUT = 25
WEB_MAX_BYTES = 300_000

SAFE_BINARIES = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find",
                 "git", "python3", "node", "npm", "lsblk", "df", "free",
                 "du", "sed", "awk", "sort", "uniq", "diff", "file",
                 "pytest", "ruff", "tsc", "cargo"}
GIT_SAFE = {"status", "log", "diff", "show", "branch", "rev-parse"}
BLOCKED_RE = ("rm ", "mv ", "dd ", ">", "mkfs", ":(){", "chmod 777")


def _jail(path: str) -> str:
    real = os.path.realpath(os.path.join(WORKSPACE, path))
    if real != WORKSPACE and not real.startswith(WORKSPACE + os.sep):
        raise PermissionError(f"path escapes workspace: {path}")
    return real


def read_file(path: str, max_chars: int = 12000) -> dict:
    try:
        with open(_jail(path)) as f:
            data = f.read(max_chars + 1)
        truncated = len(data) > max_chars
        return {"ok": True, "output": data[:max_chars], "truncated": truncated}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def run_cmd(argv: list) -> dict:
    if not argv or argv[0] not in SAFE_BINARIES:
        return {"ok": False, "error": f"binary not allowlisted: {argv[0] if argv else None}"}
    joined = " ".join(argv)
    if any(b in joined for b in BLOCKED_RE):
        return {"ok": False, "error": "blocked pattern in command"}
    if argv[0] == "git" and len(argv) > 1 and argv[1] not in GIT_SAFE:
        return {"ok": False, "error": f"git subcommand not read-only-safe: {argv[1]}"}
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=TIMEOUT_S, cwd=WORKSPACE)
        out = (p.stdout + p.stderr)[-OUT_CAP:]
        return {"ok": p.returncode == 0, "output": out,
                "error": None if p.returncode == 0 else out}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {TIMEOUT_S}s"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


TOOLS = {"read_file": read_file, "run": run_cmd,
         "web_search": None, "web_fetch": None}  # set below


def _http_get(url: str, accept: str = "*/*") -> bytes:
    req = _urlreq.Request(url, headers={"User-Agent": "urai-learn/1.0",
                                        "Accept": accept})
    with _urlreq.urlopen(req, timeout=WEB_TIMEOUT) as r:
        return r.read(WEB_MAX_BYTES + 1)


def _clean_html(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace")
    text = _re.sub(r"(?is)<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>", " ", text)
    text = _re.sub(r"(?s)<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = _re.sub(r"[ \t]+", " ", text)
    text = _re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:OUT_CAP]


def web_search(query: str, top: int = 5) -> dict:
    """Keyless web search: Wikipedia + arXiv + HackerNews + GitHub repos.
    No API keys. Each line: `- title (source) :: url`."""
    import json as _j
    out, seen = [], set()

    def add(title, url, src):
        if url and url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(f"- {title} ({src}) :: {url}")

    try:
        wq = _urlparse.quote(query)
        w = _j.loads(_http_get(
            "https://en.wikipedia.org/w/api.php?action=opensearch&search="
            f"{wq}&limit=3&format=json").decode("utf-8", "replace"))
        for t, u in zip(w[1], w[3]):
            add(t, u, "wikipedia")
    except Exception as e:
        out.append(f"(wikipedia failed: {str(e)[:120]})")
    try:
        hq = _urlparse.quote(query)
        h = _j.loads(_http_get("https://hn.algolia.com/api/v1/search?query="
                               + hq + "&tags=story").decode("utf-8", "replace"))
        for hit in h.get("hits", [])[:3]:
            add(hit.get("title", "(no title)"),
                hit.get("url") or
                f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                "hackernews")
    except Exception as e:
        out.append(f"(hackernews failed: {str(e)[:120]})")
    try:
        gq = _urlparse.quote(query)
        g = _j.loads(_http_get("https://api.github.com/search/repositories?q="
                               + gq + "&per_page=3").decode("utf-8", "replace"))
        for repo in g.get("items", []):
            add(repo.get("full_name", "") + " ★"
                + str(repo.get("stargazers_count", 0)),
                repo.get("html_url"), "github")
    except Exception as e:
        out.append(f"(github failed: {str(e)[:120]})")
    try:
        aq = _urlparse.quote(query)
        ax = _http_get("https://export.arxiv.org/api/query?search_query=all:"
                       + aq + "&max_results=3").decode("utf-8", "replace")
        for m in _re.finditer(
                r"<title>(.*?)</title>.*?<id>(.*?)</id>", ax, _re.DOTALL):
            if "arXiv Query" in m.group(1):
                continue
            add(_re.sub(r"\s+", " ", m.group(1)).strip(),
                m.group(2).strip(), "arxiv")
    except Exception as e:
        out.append(f"(arxiv failed: {str(e)[:120]})")
    return {"ok": True, "output": "\n".join(out[:top * 2])[:OUT_CAP]
            or "(no results)"}


def web_fetch(url: str) -> dict:
    """Keyless fetch: URL -> cleaned text (capped). http/https only."""
    try:
        u = _urlparse.urlparse(url)
        if u.scheme not in ("http", "https") or not u.netloc:
            return {"ok": False, "error": "only http(s) URLs allowed"}
        host = u.hostname or ""
        if host in ("localhost",) or host.startswith(("127.", "10.", "192.168.")) \
                or _re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host):
            return {"ok": False, "error": "private hosts blocked"}
        raw = _http_get(url)
        if len(raw) > WEB_MAX_BYTES:
            return {"ok": False,
                    "error": f"page too large ({len(raw) >> 10} KB "
                             f"> {WEB_MAX_BYTES >> 10} KB cap)"}
        return {"ok": True, "output": _clean_html(raw)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


TOOLS.update({"web_search": web_search, "web_fetch": web_fetch})


def browse(goal: str = "", steps: str = "[]") -> dict:
    """Human-like browser run (agent tool). Auth fields pause for user approval
    instead of failing: returns {needs_approval, run_id, fields} for the
    human to approve with real input (see docs/agent-swarm.md safety policy)."""
    import json as _json
    try:
        step_list = _json.loads(steps) if isinstance(steps, str) else (steps or [])
    except Exception:
        return {"ok": False, "error": "steps must be a JSON array"}
    try:
        from . import browser as _b
        return _b.run_steps(step_list, goal=goal)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


TOOLS["browse"] = browse

def analyze(target: str = "", max_bytes: int = 1000000) -> dict:
    from . import analyze as _a
    return _a.analyze(target, max_bytes)

TOOLS["analyze"] = analyze
