"""
jev/wiki.py — Three-tier Memory / Knowledge Wiki for Urai AI
Ported from PersonalJarvis ADR-0013. stdlib only.

Tiers:
  Short-term : in-memory dict (current session)
  Mid-term   : data/workspace/sessions/*.md (last 3-5 sessions)
  Long-term  : data/workspace/{entities,concepts,projects}/*.md
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Use repo root for reliable absolute paths
_ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = Path(os.environ.get("URAI_DATA", str(_ROOT / "data" / "workspace")))
SESSIONS_DIR = BASE_DIR / "sessions"
ENTITIES_DIR = BASE_DIR / "entities"
CONCEPTS_DIR = BASE_DIR / "concepts"
PROJECTS_DIR = BASE_DIR / "projects"
LOG_FILE = BASE_DIR / "log.md"

CATEGORY_MAP: dict[str, Path] = {
    "entities": ENTITIES_DIR,
    "concepts": CONCEPTS_DIR,
    "projects": PROJECTS_DIR,
    "sessions": SESSIONS_DIR,
}

MAX_MID_TERM_SESSIONS = 5

# ---------------------------------------------------------------------------
# Short-term in-memory store (current session)
# ---------------------------------------------------------------------------

_short_term: dict[str, dict] = {}   # title -> entry dict


def _ensure_dirs() -> None:
    for d in CATEGORY_MAP.values():
        d.mkdir(parents=True, exist_ok=True)


def _slug(title: str) -> str:
    """Filesystem-safe slug from title."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", title.strip().lower())


def _md_path(title: str, category: str) -> Path:
    folder = CATEGORY_MAP.get(category, CONCEPTS_DIR)
    return folder / f"{_slug(title)}.md"


def _append_log(action: str, title: str, category: str) -> None:
    _ensure_dirs()
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"- [{ts}] **{action}** `{category}/{title}`\n")


def _parse_entry(path: Path, category: str) -> dict:
    """Parse a wiki markdown file into an entry dict."""
    raw = path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
    title = title_match.group(1) if title_match else path.stem
    tags_match = re.search(r"^tags:\s*(.+)$", raw, re.MULTILINE)
    tags = [t.strip() for t in tags_match.group(1).split(",")] if tags_match else []
    links = re.findall(r"\[\[([^\]]+)\]\]", raw)
    created_match = re.search(r"created:\s*(.+)$", raw, re.MULTILINE)
    updated_match = re.search(r"updated:\s*(.+)$", raw, re.MULTILINE)
    return {
        "title": title,
        "category": category,
        "path": str(path),
        "tags": tags,
        "links": links,
        "created": created_match.group(1).strip() if created_match else "",
        "updated": updated_match.group(1).strip() if updated_match else "",
        "content": raw,
    }


def _write_entry(title: str, content: str, category: str) -> dict:
    _ensure_dirs()
    path = _md_path(title, category)
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    existing_created = now
    if path.exists():
        old = _parse_entry(path, category)
        existing_created = old.get("created", now)

    header = (
        f"# {title}\n\n"
        f"<!-- metadata\n"
        f"created: {existing_created}\n"
        f"updated: {now}\n"
        f"category: {category}\n"
        f"-->\n\n"
    )
    full = header + content.strip() + "\n"
    path.write_text(full, encoding="utf-8")
    entry = _parse_entry(path, category)
    _short_term[title] = entry
    return entry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def wiki_add(title: str, content: str, category: str = "concepts") -> dict:
    """
    Create or overwrite a wiki page.
    Returns the entry dict.
    """
    if category not in CATEGORY_MAP:
        raise ValueError(f"Unknown category '{category}'. Choose from {list(CATEGORY_MAP)}")
    entry = _write_entry(title, content, category)
    _append_log("ADD", title, category)
    return entry


def wiki_get(title: str) -> Optional[dict]:
    """
    Retrieve a wiki page by exact title.
    Checks short-term cache first, then disk (all categories).
    """
    if title in _short_term:
        return _short_term[title]
    slug = _slug(title)
    for category, folder in CATEGORY_MAP.items():
        p = folder / f"{slug}.md"
        if p.exists():
            entry = _parse_entry(p, category)
            _short_term[title] = entry
            return entry
    return None


def wiki_search(query: str, top: int = 5) -> list[dict]:
    """
    BM25-style keyword search across all long-term wiki files.
    Returns top-N ranked entries.
    """
    _ensure_dirs()
    tokens = re.findall(r"\w+", query.lower())
    if not tokens:
        return []

    # Collect all documents
    docs: list[tuple[Path, str]] = []
    for category, folder in CATEGORY_MAP.items():
        if category == "sessions":
            continue
        for p in folder.glob("*.md"):
            docs.append((p, category))

    if not docs:
        return []

    # TF for each doc
    def tokenize(text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    corpus: list[list[str]] = []
    for p, _ in docs:
        corpus.append(tokenize(p.read_text(encoding="utf-8")))

    # IDF
    N = len(corpus)
    df: dict[str, int] = defaultdict(int)
    for doc_tokens in corpus:
        unique = set(doc_tokens)
        for t in unique:
            df[t] += 1

    k1, b = 1.5, 0.75
    avg_dl = sum(len(d) for d in corpus) / max(N, 1)

    scores: list[float] = []
    for doc_tokens in corpus:
        dl = len(doc_tokens)
        tf_map: dict[str, int] = defaultdict(int)
        for t in doc_tokens:
            tf_map[t] += 1
        score = 0.0
        for token in tokens:
            if token not in df:
                continue
            idf = math.log((N - df[token] + 0.5) / (df[token] + 0.5) + 1)
            tf = tf_map.get(token, 0)
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * dl / avg_dl)
            score += idf * (numerator / denominator)
        scores.append(score)

    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    results = []
    for idx, score in ranked[:top]:
        if score <= 0:
            break
        p, category = docs[idx]
        entry = _parse_entry(p, category)
        entry["score"] = round(score, 4)
        results.append(entry)
    return results


def wiki_update(title: str, new_facts: list[str]) -> dict:
    """
    Append new facts to an existing wiki page without rewriting.
    Creates the page if it doesn't exist yet.
    """
    existing = wiki_get(title)
    if existing:
        category = existing["category"]
        path = Path(existing["path"])
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        additions = "\n".join(f"- {fact}" for fact in new_facts)
        block = f"\n\n## Updates ({now})\n\n{additions}\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(block)
        # patch updated timestamp in header
        raw = path.read_text(encoding="utf-8")
        raw = re.sub(r"(updated:\s*)[\S]+", f"\\g<1>{now}", raw)
        path.write_text(raw, encoding="utf-8")
        entry = _parse_entry(path, category)
        _short_term[title] = entry
        _append_log("UPDATE", title, category)
        return entry
    else:
        content = "\n".join(f"- {fact}" for fact in new_facts)
        return wiki_add(title, content)


def wiki_list(category: str = "") -> list[dict]:
    """
    List all wiki pages, optionally filtered by category.
    """
    _ensure_dirs()
    results = []
    cats = {category: CATEGORY_MAP[category]} if category in CATEGORY_MAP else CATEGORY_MAP
    for cat, folder in cats.items():
        if cat == "sessions":
            continue
        for p in sorted(folder.glob("*.md")):
            entry = _parse_entry(p, cat)
            results.append({
                "title": entry["title"],
                "category": cat,
                "path": str(p),
                "updated": entry["updated"],
                "links": entry["links"],
            })
    return results


def wiki_link(from_title: str, to_title: str) -> dict:
    """
    Append a [[wikilink]] from one page to another.
    Creates source page stub if missing.
    """
    source = wiki_get(from_title)
    if source is None:
        source = wiki_add(from_title, f"See also: [[{to_title}]]")
    else:
        path = Path(source["path"])
        link_text = f"\n- [[{to_title}]]\n"
        # avoid duplicate links
        raw = path.read_text(encoding="utf-8")
        if f"[[{to_title}]]" not in raw:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(link_text)
            now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            raw = path.read_text(encoding="utf-8")
            raw = re.sub(r"(updated:\s*)[\S]+", f"\\g<1>{now}", raw)
            path.write_text(raw, encoding="utf-8")
        source = _parse_entry(path, source["category"])
        _short_term[from_title] = source
    _append_log("LINK", f"{from_title} -> {to_title}", source["category"])
    return source


def session_save(session_id: str, summary: str) -> dict:
    """
    Save a mid-term session summary to data/workspace/sessions/.
    Prunes oldest sessions if count exceeds MAX_MID_TERM_SESSIONS.
    """
    _ensure_dirs()
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    filename = f"{session_id}.md"
    path = SESSIONS_DIR / filename
    content = (
        f"# Session {session_id}\n\n"
        f"<!-- metadata\n"
        f"created: {now}\n"
        f"updated: {now}\n"
        f"category: sessions\n"
        f"-->\n\n"
        f"{summary.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    _append_log("SESSION_SAVE", session_id, "sessions")

    # Prune oldest sessions
    all_sessions = sorted(SESSIONS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    while len(all_sessions) > MAX_MID_TERM_SESSIONS:
        oldest = all_sessions.pop(0)
        oldest.unlink()

    return {
        "session_id": session_id,
        "path": str(path),
        "saved_at": now,
    }


def context_inject(query: str) -> str:
    """
    Build a context string for system-prompt injection.
    Pulls relevant wiki pages (BM25) + recent sessions + short-term cache.
    """
    lines: list[str] = ["## Urai Knowledge Context\n"]

    # Short-term (current session cache)
    if _short_term:
        lines.append("### Recent (this session)")
        for title, entry in list(_short_term.items())[-3:]:
            snippet = entry["content"][:300].replace("\n", " ")
            lines.append(f"- **{title}**: {snippet}…")
        lines.append("")

    # Mid-term: recent sessions
    _ensure_dirs()
    sessions = sorted(SESSIONS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if sessions:
        lines.append("### Recent Sessions")
        for s in sessions[:3]:
            raw = s.read_text(encoding="utf-8")
            first_para = raw.split("\n\n")[2] if len(raw.split("\n\n")) > 2 else raw[:200]
            lines.append(f"- **{s.stem}**: {first_para[:200].replace(chr(10),' ')}…")
        lines.append("")

    # Long-term: BM25 search
    hits = wiki_search(query, top=5)
    if hits:
        lines.append("### Relevant Knowledge")
        for h in hits:
            snippet = h["content"][:400].replace("\n", " ")
            lines.append(f"- **{h['title']}** ({h['category']}): {snippet}…")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

def _reinit_paths(tmp: str) -> None:
    global BASE_DIR, SESSIONS_DIR, ENTITIES_DIR, CONCEPTS_DIR, PROJECTS_DIR, LOG_FILE, CATEGORY_MAP
    BASE_DIR = Path(tmp)
    SESSIONS_DIR = BASE_DIR / "sessions"
    ENTITIES_DIR = BASE_DIR / "entities"
    CONCEPTS_DIR = BASE_DIR / "concepts"
    PROJECTS_DIR = BASE_DIR / "projects"
    LOG_FILE = BASE_DIR / "log.md"
    CATEGORY_MAP = {
        "entities": ENTITIES_DIR,
        "concepts": CONCEPTS_DIR,
        "projects": PROJECTS_DIR,
        "sessions": SESSIONS_DIR,
    }


if __name__ == "__main__":
    import tempfile, sys

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["URAI_DATA"] = tmp
        _reinit_paths(tmp)
        _short_term.clear()

        e = wiki_add("Python", "A high-level programming language.", "concepts")
        print("ADD:", e["title"])

        wiki_update("Python", ["Supports async/await", "Used in AI/ML"])
        g = wiki_get("Python")
        print("GET:", g["title"], "| links:", g["links"])

        wiki_add("AsyncIO", "Python async library.", "concepts")
        wiki_link("Python", "AsyncIO")

        results = wiki_search("async python programming", top=3)
        print("SEARCH:", [(r["title"], r["score"]) for r in results])

        lst = wiki_list("concepts")
        print("LIST:", [x["title"] for x in lst])

        s = session_save("sess_001", "Discussed Python async patterns.")
        print("SESSION:", s["session_id"])

        ctx = context_inject("python async")
        print("CONTEXT (preview):", ctx[:300])
        print("OK — all tests passed.")
