"""
jev/research.py — Deep research engine for the Urai AI project.

Ported from Odysseus's IterResearch (odysseus-dev/odysseus deep_research.py),
adapted for Urai's local-first, stdlib-only architecture.

Key differences from Odysseus:
  - All LLM calls go through Urai's LlamaServerBackend (local llama.cpp server)
    instead of remote APIs (OpenAI, Anthropic, etc.)
  - Web I/O uses Urai's own web_search / web_fetch tools (tools.py) rather
    than Playwright or httpx.
  - Zero third-party dependencies — stdlib only (urllib, threading, json, …)
  - Graceful degradation: if the local LLM is unavailable the module falls back
    to keyword-only multi-hop search so the caller always gets *something*.

Algorithm overview (mirrors IterResearch's iterative loop):
  Round 0  — Build a structured research plan (sub-questions, key topics,
              success criteria) by prompting the LLM.
  Round 1-N — For each round:
               1. Generate N search queries informed by the plan and prior facts.
               2. Execute queries in parallel (threading.Thread + urllib).
               3. Fetch the top-ranked URLs, score by source quality.
               4. Extract candidate facts from the fetched HTML/text.
               5. Ask the LLM "do we have enough to answer the original query?"
               6. Break early when sufficient, otherwise iterate.
  Final     — Synthesize all gathered facts into a cited, comprehensive answer.

Public API
----------
  deep_research(query, depth=4, max_rounds=3) -> dict
  research_plan(query)                         -> dict
  assess_sufficiency(query, gathered_text)     -> bool
  synthesize(query, plan, all_facts, sources)  -> dict

All public functions return dicts and never raise; errors surface as
  {"ok": False, "error": "<message>"}.

Usage example::

    from jev.research import deep_research
    result = deep_research("What causes aurora borealis?", depth=3)
    if result["ok"]:
        print(result["answer"])

"""

from __future__ import annotations

import html
import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Lazy relative imports — tolerate running the file standalone for testing
# ---------------------------------------------------------------------------
try:
    from .tools import web_fetch as _tools_web_fetch
    from .tools import web_search as _tools_web_search
    _HAS_TOOLS = True
except ImportError:
    _HAS_TOOLS = False

try:
    from .llm import LlamaServerBackend
    _HAS_LLM = True
except ImportError:
    _HAS_LLM = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_LLAMA_URL   = "http://127.0.0.1:8080"
_LLM_TIMEOUT_S       = 30          # seconds to wait for a local LLM response
_FETCH_TIMEOUT_S     = 10          # seconds to wait for a URL fetch
_MAX_SOURCES_ROUND   = 10          # deduplicated sources kept per round
_MAX_FACT_CHARS      = 400         # characters kept from each fetched page
_MAX_CONTEXT_CHARS   = 8_000       # total characters sent to LLM as context
_DEFAULT_DEPTH       = 4           # search queries per round
_DEFAULT_MAX_ROUNDS  = 3

# Source-quality domain tiers (higher = better)
_DOMAIN_SCORES: dict[str, int] = {
    ".gov": 10, ".edu": 9,
    "reuters.com": 8, "apnews.com": 8, "bbc.com": 8, "bbc.co.uk": 8,
    "nature.com": 8, "science.org": 8, "sciencedirect.com": 8,
    "pubmed.ncbi.nlm.nih.gov": 9, "ncbi.nlm.nih.gov": 9,
    "nytimes.com": 7, "theguardian.com": 7, "washingtonpost.com": 7,
    "economist.com": 7, "ft.com": 7, "bloomberg.com": 7,
    "stackoverflow.com": 6, "github.com": 6, "arxiv.org": 8,
    "wikipedia.org": 5,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today_str() -> str:
    """Return today's date as 'YYYY-MM-DD' in UTC."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _score_url(url: str) -> int:
    """Return a quality score for *url* based on its domain."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return 0
    for pattern, score in _DOMAIN_SCORES.items():
        if host.endswith(pattern) or pattern in host:
            return score
    return 1


def _strip_html(text: str) -> str:
    """Very lightweight HTML tag stripper (no dependencies)."""
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style[^>]*>.*?</style>",  " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _dedupe_urls(urls: list[str], seen: set[str]) -> list[str]:
    """Return *urls* that are not already in *seen*, updating *seen* in-place."""
    fresh: list[str] = []
    for u in urls:
        norm = u.strip().rstrip("/")
        if norm and norm not in seen:
            seen.add(norm)
            fresh.append(norm)
    return fresh


# ---------------------------------------------------------------------------
# LLM gateway (thin wrapper around LlamaServerBackend or raw HTTP fallback)
# ---------------------------------------------------------------------------

class _LLMGateway:
    """
    Thin wrapper that calls the local llama.cpp server.

    Falls back to a raw HTTP POST to /completion if LlamaServerBackend is
    not importable (e.g. when running the module standalone for testing).
    """

    def __init__(self, base_url: str = _DEFAULT_LLAMA_URL):
        self._base_url = base_url.rstrip("/")
        self._backend: Any = None
        if _HAS_LLM:
            try:
                self._backend = LlamaServerBackend(base_url=base_url)
                log.debug("LlamaServerBackend initialised at %s", base_url)
            except Exception as exc:
                log.warning("Could not init LlamaServerBackend: %s", exc)

    def complete(self, prompt: str, max_tokens: int = 512) -> str | None:
        """
        Send *prompt* to the LLM and return the response text, or None on
        failure.
        """
        # --- attempt via LlamaServerBackend ---
        if self._backend is not None:
            try:
                return self._backend.complete(prompt, max_tokens=max_tokens)
            except Exception as exc:
                log.warning("LlamaServerBackend.complete failed: %s", exc)

        # --- raw HTTP fallback ---
        return self._raw_complete(prompt, max_tokens)

    def _raw_complete(self, prompt: str, max_tokens: int) -> str | None:
        payload = json.dumps({
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": 0.3,
            "stop": ["</s>", "### Human", "### Assistant"],
        }).encode()
        req = urllib.request.Request(
            f"{self._base_url}/completion",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT_S) as resp:
                body = json.loads(resp.read().decode())
                return body.get("content") or body.get("text")
        except Exception as exc:
            log.warning("Raw LLM call failed: %s", exc)
            return None

    @property
    def available(self) -> bool:
        """Quick liveness check — True if the server responds at all."""
        try:
            req = urllib.request.Request(
                f"{self._base_url}/health", method="GET"
            )
            with urllib.request.urlopen(req, timeout=3):
                return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Web search / fetch layer (delegates to tools.py when available)
# ---------------------------------------------------------------------------

def _web_search(query: str) -> list[dict]:
    """
    Run a web search for *query* and return a list of result dicts
    with at least {"url": str, "title": str, "snippet": str} keys.
    """
    if _HAS_TOOLS:
        try:
            results = _tools_web_search(query)
            if isinstance(results, list):
                return results
        except Exception as exc:
            log.warning("tools.web_search failed: %s", exc)

    # Minimal DuckDuckGo HTML fallback (stdlib only)
    return _ddg_search(query)


def _ddg_search(query: str) -> list[dict]:
    """
    Scrape DuckDuckGo HTML results as a last-resort fallback.
    Returns up to 10 results.
    """
    encoded = urllib.parse.quote_plus(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) "
            "Gecko/20100101 Firefox/115.0"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("DDG search failed: %s", exc)
        return []

    results: list[dict] = []
    # Parse result blocks — fragile but dependency-free
    blocks = re.findall(
        r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        raw, flags=re.S
    )
    for href, title_html in blocks[:10]:
        # DDG redirects look like //duckduckgo.com/l/?uddg=<encoded_url>
        match = re.search(r"uddg=([^&]+)", href)
        if match:
            href = urllib.parse.unquote(match.group(1))
        results.append({
            "url": href,
            "title": _strip_html(title_html).strip(),
            "snippet": "",
        })
    return results


def _web_fetch_url(url: str) -> str:
    """
    Fetch the text content of *url*, returning a plain-text excerpt.
    """
    if _HAS_TOOLS:
        try:
            content = _tools_web_fetch(url)
            if isinstance(content, str) and content:
                return _strip_html(content)
        except Exception as exc:
            log.warning("tools.web_fetch failed for %s: %s", url, exc)

    # stdlib urllib fallback
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; UraiFetcher/1.0)"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
            raw = resp.read(65_536).decode("utf-8", errors="replace")
        return _strip_html(raw)
    except Exception as exc:
        log.debug("Fetch failed for %s: %s", url, exc)
        return ""


def _parallel_fetch(urls: list[str]) -> dict[str, str]:
    """
    Fetch all *urls* concurrently using threading.Thread.
    Returns {url: text_content} for each URL that responded.
    """
    results: dict[str, str] = {}
    lock = threading.Lock()

    def worker(u: str) -> None:
        text = _web_fetch_url(u)
        if text:
            with lock:
                results[u] = text

    threads = [threading.Thread(target=worker, args=(u,), daemon=True)
               for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=_FETCH_TIMEOUT_S + 2)

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def research_plan(query: str, llm: _LLMGateway | None = None) -> dict:
    """
    Ask the LLM to produce a structured research plan for *query*.

    Returns::

        {
          "ok": True,
          "sub_questions": ["...", ...],
          "key_topics":    ["...", ...],
          "success_criteria": "...",
        }

    On LLM failure returns a keyword-derived fallback plan with ok=True so
    callers can always proceed.
    """
    if llm is None:
        llm = _LLMGateway()

    prompt = (
        f"Today is {_today_str()}.\n\n"
        "You are a research planning assistant. Given the query below, produce a "
        "JSON object (no markdown, no extra text) with exactly these keys:\n"
        '  "sub_questions": a list of 3-5 specific questions to answer\n'
        '  "key_topics":    a list of 3-6 important topics/entities to research\n'
        '  "success_criteria": one sentence describing what a complete answer looks like\n\n'
        f'Query: """{query}"""\n\n'
        "JSON:"
    )

    raw = llm.complete(prompt, max_tokens=512)
    if raw:
        # Extract the first JSON object from the response
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if match:
            try:
                plan = json.loads(match.group())
                plan.setdefault("sub_questions", [])
                plan.setdefault("key_topics", [])
                plan.setdefault("success_criteria", "")
                plan["ok"] = True
                return plan
            except json.JSONDecodeError as exc:
                log.warning("research_plan JSON parse error: %s", exc)

    # Keyword-only fallback
    log.info("research_plan: LLM unavailable, using keyword fallback")
    words = [w for w in re.split(r"\W+", query) if len(w) > 3]
    return {
        "ok": True,
        "sub_questions": [
            f"What is {query}?",
            f"What are the main causes or components of {query}?",
            f"What are recent developments related to {query}?",
        ],
        "key_topics": words[:6],
        "success_criteria": (
            f"A comprehensive answer covering the main aspects of: {query}"
        ),
        "_fallback": True,
    }


def assess_sufficiency(
    query: str,
    gathered_text: str,
    llm: _LLMGateway | None = None,
) -> bool:
    """
    Ask the LLM whether *gathered_text* contains enough information to
    fully answer *query*.

    Returns True if sufficient, False otherwise.
    Falls back to a heuristic (length check) if the LLM is unavailable.
    """
    if llm is None:
        llm = _LLMGateway()

    context = _truncate(gathered_text, _MAX_CONTEXT_CHARS)
    prompt = (
        f"Today is {_today_str()}.\n\n"
        "Assess whether the GATHERED INFORMATION below is sufficient to give a "
        "comprehensive, accurate answer to the QUERY.\n\n"
        f'QUERY: """{query}"""\n\n'
        f"GATHERED INFORMATION:\n{context}\n\n"
        'Reply with exactly one word — either "YES" or "NO" — '
        "then optionally a one-sentence reason.\n"
        "Answer:"
    )

    raw = llm.complete(prompt, max_tokens=64)
    if raw:
        answer = raw.strip().upper()
        if answer.startswith("YES"):
            return True
        if answer.startswith("NO"):
            return False

    # Heuristic fallback: if we have at least 800 chars, assume enough
    return len(gathered_text) >= 800


def synthesize(
    query: str,
    plan: dict,
    all_facts: list[str],
    sources: list[dict],
    llm: _LLMGateway | None = None,
) -> dict:
    """
    Synthesize all gathered facts into a comprehensive, cited answer.

    Returns::

        {
          "ok": True,
          "answer": "...",
          "citations": ["url1", "url2", ...],
        }
    """
    if llm is None:
        llm = _LLMGateway()

    # Build a numbered source list for the LLM to cite
    source_urls = [s["url"] for s in sources if "url" in s]
    numbered = "\n".join(
        f"[{i+1}] {url}" for i, url in enumerate(source_urls[:20])
    )

    facts_text = "\n\n".join(f"• {f}" for f in all_facts)
    facts_text = _truncate(facts_text, _MAX_CONTEXT_CHARS)

    sub_q_text = "\n".join(
        f"  - {q}" for q in plan.get("sub_questions", [])
    )
    criteria = plan.get("success_criteria", "")

    prompt = (
        f"Today is {_today_str()}.\n\n"
        "You are a research synthesis assistant. Using ONLY the facts below, "
        "write a comprehensive, well-structured answer to the QUERY. "
        "Cite sources using [N] notation where N matches the SOURCE LIST.\n\n"
        f'QUERY: """{query}"""\n\n'
        f"SUB-QUESTIONS TO ADDRESS:\n{sub_q_text}\n\n"
        f"SUCCESS CRITERIA: {criteria}\n\n"
        f"SOURCE LIST:\n{numbered}\n\n"
        f"GATHERED FACTS:\n{facts_text}\n\n"
        "COMPREHENSIVE ANSWER:"
    )

    raw = llm.complete(prompt, max_tokens=1024)
    if not raw:
        # Fallback: concatenate facts
        raw = (
            f"Research summary for: {query}\n\n"
            + "\n".join(f"• {f}" for f in all_facts[:20])
        )
        log.info("synthesize: LLM unavailable, using concatenation fallback")

    return {
        "ok": True,
        "answer": raw.strip(),
        "citations": source_urls,
    }


def _generate_queries(
    query: str,
    plan: dict,
    facts_so_far: list[str],
    round_num: int,
    depth: int,
    llm: _LLMGateway,
) -> list[str]:
    """
    Ask the LLM to generate *depth* web search queries for the current round.
    Falls back to template-based queries if the LLM is unavailable.
    """
    today = _today_str()
    sub_q = plan.get("sub_questions", [])
    topics = plan.get("key_topics", [])
    known_snippet = _truncate("\n".join(facts_so_far[-5:]), 600)

    prompt = (
        f"Today is {today}.\n\n"
        f"You are generating web search queries for round {round_num} of "
        f"researching: \"{query}\"\n\n"
        f"Sub-questions to address: {json.dumps(sub_q)}\n"
        f"Key topics: {json.dumps(topics)}\n"
        f"What we know so far (latest facts):\n{known_snippet}\n\n"
        f"Generate exactly {depth} diverse, specific web search queries that "
        "will help fill gaps in our knowledge. Include the current year or "
        f"'{today}' in at least one query to get fresh results.\n"
        f"Return only a JSON array of {depth} strings.\n"
        "Queries:"
    )

    raw = llm.complete(prompt, max_tokens=256)
    if raw:
        match = re.search(r"\[.*\]", raw, flags=re.S)
        if match:
            try:
                queries = json.loads(match.group())
                if isinstance(queries, list) and queries:
                    return [str(q) for q in queries[:depth]]
            except json.JSONDecodeError:
                pass

    # Template fallback
    year = today[:4]
    base_queries = [
        f"{query} {year}",
        f"{query} explained",
        f"{query} latest research",
        f"{query} overview",
        f"{query} examples",
        f"{query} causes effects",
    ]
    for topic in topics[:2]:
        base_queries.append(f"{topic} {query}")
    return base_queries[:depth]


def _extract_facts(url: str, text: str, query: str) -> list[str]:
    """
    Extract candidate fact sentences from *text* that are relevant to *query*.
    Returns a list of short fact strings (at most _MAX_FACT_CHARS each).
    """
    if not text:
        return []

    # Split into sentences (simple heuristic)
    sentences = re.split(r"(?<=[.!?])\s+", text)

    # Score sentences by keyword overlap with the query
    query_words = set(re.split(r"\W+", query.lower()))
    query_words = {w for w in query_words if len(w) > 3}

    scored: list[tuple[int, str]] = []
    for sent in sentences:
        if len(sent) < 20 or len(sent) > 600:
            continue
        sent_words = set(re.split(r"\W+", sent.lower()))
        overlap = len(query_words & sent_words)
        if overlap > 0:
            scored.append((overlap, sent.strip()))

    scored.sort(key=lambda x: -x[0])
    top = [s for _, s in scored[:5]]
    return [_truncate(s, _MAX_FACT_CHARS) for s in top]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def deep_research(
    query: str,
    depth: int = _DEFAULT_DEPTH,
    max_rounds: int = _DEFAULT_MAX_ROUNDS,
    llama_url: str = _DEFAULT_LLAMA_URL,
) -> dict:
    """
    Run iterative deep research on *query*.

    Parameters
    ----------
    query      : The research question or topic.
    depth      : Number of search queries generated per round (default 4).
    max_rounds : Maximum research iterations beyond round 0 (default 3).
    llama_url  : Base URL of the local llama.cpp server.

    Returns
    -------
    dict with keys:
      ok           : bool
      answer       : str  — synthesized, cited answer
      sources      : list[dict]  — {"url", "title", "score"} per source
      sub_questions: list[str]
      rounds_used  : int
      elapsed_s    : float
      error        : str  (only present when ok=False)
    """
    t_start = time.monotonic()
    log.info("deep_research started: %r  depth=%d  max_rounds=%d",
             query, depth, max_rounds)

    llm = _LLMGateway(base_url=llama_url)
    llm_live = llm.available
    if not llm_live:
        log.warning("LLM server not reachable at %s — keyword-only mode", llama_url)

    # --- Round 0: research plan ---
    plan = research_plan(query, llm=llm)
    if not plan.get("ok"):
        return {"ok": False, "error": f"research_plan failed: {plan.get('error')}"}

    log.info("Research plan: sub_questions=%s  key_topics=%s",
             plan["sub_questions"], plan["key_topics"])

    all_facts:   list[str]       = []
    all_sources: list[dict]      = []
    seen_urls:   set[str]        = set()
    rounds_used: int             = 0

    # --- Rounds 1-N ---
    for round_num in range(1, max_rounds + 1):
        rounds_used = round_num
        log.info("=== Round %d ===", round_num)

        # 1. Generate search queries
        queries = _generate_queries(
            query, plan, all_facts, round_num, depth, llm
        )
        log.debug("Round %d queries: %s", round_num, queries)

        # 2. Execute searches in parallel
        search_results_q: queue.Queue[list[dict]] = queue.Queue()

        def _search_worker(q: str, out: queue.Queue) -> None:  # noqa: ANN001
            out.put(_web_search(q))

        search_threads = [
            threading.Thread(
                target=_search_worker, args=(q, search_results_q), daemon=True
            )
            for q in queries
        ]
        for t in search_threads:
            t.start()
        for t in search_threads:
            t.join(timeout=_FETCH_TIMEOUT_S + 2)

        # Collect and rank results
        candidate_urls: list[tuple[int, str, str]] = []  # (score, url, title)
        while not search_results_q.empty():
            results = search_results_q.get_nowait()
            for r in results:
                url = r.get("url", "").strip()
                if not url:
                    continue
                title = r.get("title", "")
                score = _score_url(url)
                candidate_urls.append((score, url, title))

        # Sort by quality score, deduplicate
        candidate_urls.sort(key=lambda x: -x[0])
        fresh_urls = _dedupe_urls(
            [u for _, u, _ in candidate_urls], seen_urls
        )[:_MAX_SOURCES_ROUND]

        if not fresh_urls:
            log.info("Round %d: no new URLs found", round_num)
            if round_num < max_rounds:
                continue
            break

        # 3. Fetch URLs in parallel
        url_score_map = {u: s for s, u, _ in candidate_urls}
        url_title_map = {u: t for _, u, t in candidate_urls}
        fetched = _parallel_fetch(fresh_urls)

        # 4. Extract facts
        round_facts: list[str] = []
        for url, text in fetched.items():
            facts = _extract_facts(url, text, query)
            if facts:
                round_facts.extend(facts)
                all_sources.append({
                    "url": url,
                    "title": url_title_map.get(url, ""),
                    "score": url_score_map.get(url, 1),
                    "round": round_num,
                })

        all_facts.extend(round_facts)
        log.info("Round %d: fetched %d URLs, extracted %d facts",
                 round_num, len(fetched), len(round_facts))

        # 5. Check sufficiency
        if all_facts:
            gathered_text = " ".join(all_facts)
            if assess_sufficiency(query, gathered_text, llm=llm):
                log.info("Round %d: sufficiency check passed — stopping early",
                         round_num)
                break
        else:
            log.info("Round %d: no facts gathered yet", round_num)

    # --- Final synthesis ---
    if not all_facts:
        # Nothing useful found at all
        elapsed = time.monotonic() - t_start
        return {
            "ok": False,
            "error": "No usable information found for the query.",
            "answer": "",
            "sources": [],
            "sub_questions": plan.get("sub_questions", []),
            "rounds_used": rounds_used,
            "elapsed_s": round(elapsed, 2),
        }

    synthesis = synthesize(query, plan, all_facts, all_sources, llm=llm)

    # Deduplicate and sort sources by quality score
    seen_src: set[str] = set()
    unique_sources: list[dict] = []
    for src in sorted(all_sources, key=lambda s: -s.get("score", 0)):
        if src["url"] not in seen_src:
            seen_src.add(src["url"])
            unique_sources.append(src)

    elapsed = time.monotonic() - t_start
    log.info("deep_research complete in %.1fs using %d sources",
             elapsed, len(unique_sources))

    return {
        "ok": True,
        "answer": synthesis.get("answer", ""),
        "sources": unique_sources,
        "sub_questions": plan.get("sub_questions", []),
        "rounds_used": rounds_used,
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# CLI smoke-test (python -m jev.research "your query")
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    )

    _query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is quantum entanglement?"
    print(f"\n🔍  Query: {_query}\n")

    _result = deep_research(_query, depth=3, max_rounds=2)

    if _result.get("ok"):
        print("=" * 72)
        print(_result["answer"])
        print("=" * 72)
        print(f"\n📚  Sources ({len(_result['sources'])}):")
        for s in _result["sources"][:10]:
            print(f"  [{s.get('score','-')}] {s['url']}")
        print(f"\n⏱   Elapsed: {_result['elapsed_s']}s over {_result['rounds_used']} round(s)")
    else:
        print(f"❌  Error: {_result.get('error')}")
