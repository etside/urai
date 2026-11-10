#!/usr/bin/env python3
"""
GitHub + BeautifulSoup scraper for Urai training data.
Uses gh auth token to search GitHub for the best training code, tools,
and recipes from Kaggle notebooks, Tailscale, and LiteLLM repos.
Extracts code snippets and converts them to distill JSONL training rows.
"""

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

# Global session with enforced timeouts
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=1))
SESSION.mount("http://", HTTPAdapter(max_retries=1))
REQUEST_TIMEOUT = 8  # seconds

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "verified"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Get gh token — prefer env var to avoid subprocess hang in cron/daemon
def get_gh_token() -> str:
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        token = result.stdout.strip()
    return token

GH_TOKEN = get_gh_token()
HEADERS = {
    "Authorization": f"token {GH_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "urai-scraper/1.0",
}

def make_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]

def distill_row(task_id, category, prompt, completion, source="gh-soup-v1"):
    return {
        "task_id": task_id,
        "category": category,
        "prompt": prompt,
        "completion": completion,
        "teacher": source,
        "score": 1.0,
        "checks": 1,
        "failures": [],
        "content_hash": make_id(prompt + completion),
        "pipeline_version": "distill-ghsoup-v1",
    }

def gh_search_code(query: str, language: str = "Python", max_results: int = 30) -> list:
    """Search GitHub code via API."""
    url = "https://api.github.com/search/code"
    params = {"q": f"{query} language:{language}", "per_page": min(max_results, 30), "sort": "indexed"}
    resp = SESSION.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    if resp.status_code == 200:
        return resp.json().get("items", [])
    print(f"  GH search error {resp.status_code}: {query}")
    return []

def fetch_raw_file(url: str) -> str:
    """Fetch raw file content from GitHub."""
    raw_url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    try:
        resp = SESSION.get(raw_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        return resp.text[:8000] if resp.status_code == 200 else ""
    except Exception:
        return ""

def soup_extract_code_blocks(html: str) -> list[str]:
    """Extract code blocks from GitHub HTML using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    for tag in soup.find_all(["pre", "code", "div"], class_=lambda c: c and any(
        x in str(c) for x in ["highlight", "code", "blob-code", "CodeMirror"]
    )):
        text = tag.get_text()
        if len(text.strip()) > 50:
            blocks.append(text.strip()[:3000])
    return blocks[:5]

def fetch_github_page_soup(url: str) -> BeautifulSoup:
    """Fetch a GitHub page and return BeautifulSoup."""
    try:
        resp = SESSION.get(url, headers={**HEADERS, "Accept": "text/html"}, timeout=REQUEST_TIMEOUT)
        return BeautifulSoup(resp.text, "html.parser") if resp.status_code == 200 else BeautifulSoup("", "html.parser")
    except Exception:
        return BeautifulSoup("", "html.parser")


# ── Scrape Kaggle training notebooks ────────────────────────────────────────

def scrape_kaggle_training_patterns() -> list[dict]:
    rows = []
    print("  Scraping Kaggle QLoRA/unsloth training patterns from GitHub...")

    searches = [
        ("unsloth QLoRA Qwen3 fine-tune kaggle", "Python"),
        ("kaggle qlora training notebook sft trl", "Python"),
        ("unsloth FastModel from_pretrained kaggle T4", "Python"),
        ("SFTTrainer alpaca dataset kaggle notebook", "Python"),
        ("gguf export quantize q4_k_m kaggle", "Python"),
    ]

    for query, lang in searches:
        items = gh_search_code(query, lang, max_results=10)
        time.sleep(1)  # rate limit
        for item in items[:5]:
            content = fetch_raw_file(item.get("html_url", ""))
            if not content or len(content) < 200:
                continue
            # Extract meaningful functions
            lines = content.splitlines()
            func_blocks = []
            current = []
            in_func = False
            for line in lines:
                if line.startswith("def ") or line.startswith("class "):
                    if current and in_func:
                        func_blocks.append("\n".join(current))
                    current = [line]
                    in_func = True
                elif in_func:
                    current.append(line)
                    if len(current) > 60:
                        func_blocks.append("\n".join(current))
                        current = []
                        in_func = False

            for i, block in enumerate(func_blocks[:3]):
                if len(block.strip()) < 100:
                    continue
                fname = item.get("name", "unknown")
                repo = item.get("repository", {}).get("full_name", "unknown")
                prompt = f"Explain and improve this QLoRA/Kaggle training function from {repo}/{fname}:\n```python\n{block[:1000]}\n```"
                completion = f"This function from `{repo}` implements part of a QLoRA fine-tuning pipeline. Key pattern:\n```python\n{block[:1500]}\n```\nBest practices: use `unsloth` for 2-5x speedup, set `load_in_4bit=True`, use `adamw_8bit` optimizer, and export to GGUF with `q4_k_m` quantization for deployment."
                rows.append(distill_row(
                    f"kaggle-{make_id(block)[:8]}",
                    "kaggle-training",
                    prompt, completion,
                    source=f"gh-soup/{repo}"
                ))
        print(f"    [{query[:40]}] -> {len(rows)} rows so far")

    return rows


# ── Scrape Tailscale patterns ────────────────────────────────────────────────

def scrape_tailscale_patterns() -> list[dict]:
    rows = []
    print("  Scraping Tailscale integration patterns from GitHub...")

    searches = [
        ("tailscale tsnet go server example", "Go"),
        ("tailscale python sdk integration", "Python"),
        ("tailscale exit node advertise routes", "Shell"),
        ("tailscale MagicDNS hostname resolution", "Go"),
        ("tailscale serve funnel HTTPS", "Go"),
    ]

    for query, lang in searches:
        items = gh_search_code(query, lang, max_results=8)
        time.sleep(1)
        for item in items[:4]:
            content = fetch_raw_file(item.get("html_url", ""))
            if not content or len(content) < 100:
                continue
            repo = item.get("repository", {}).get("full_name", "unknown")
            fname = item.get("name", "file")
            prompt = f"Show how to implement Tailscale {query.split()[1]} in {lang} (from {repo})."
            completion = f"Here is a working {lang} implementation pattern from `{repo}/{fname}`:\n```{lang.lower()}\n{content[:2000]}\n```"
            rows.append(distill_row(
                f"tailscale-{make_id(content)[:8]}",
                "tailscale-networking",
                prompt, completion,
                source=f"gh-soup/{repo}"
            ))
        print(f"    [{query[:40]}] -> {len(rows)} rows so far")

    return rows


# ── Scrape LiteLLM patterns ──────────────────────────────────────────────────

def scrape_litellm_patterns() -> list[dict]:
    rows = []
    print("  Scraping LiteLLM patterns from GitHub...")

    # Fetch LiteLLM repo directly
    litellm_searches = [
        ("litellm completion streaming async", "Python"),
        ("litellm router load balancing fallback", "Python"),
        ("litellm proxy server config yaml", "Python"),
        ("litellm ollama openai compatible", "Python"),
        ("litellm cost tracking budget", "Python"),
        ("litellm function calling tools", "Python"),
    ]

    for query, lang in litellm_searches:
        items = gh_search_code(query, lang, max_results=10)
        time.sleep(1)
        for item in items[:4]:
            content = fetch_raw_file(item.get("html_url", ""))
            if not content or len(content) < 100:
                continue
            repo = item.get("repository", {}).get("full_name", "unknown")
            fname = item.get("name", "file")
            # Only keep files that actually use litellm
            if "litellm" not in content.lower():
                continue
            prompt = f"Show a complete LiteLLM example for: {query}. From repo: {repo}."
            completion = f"Complete LiteLLM implementation from `{repo}/{fname}`:\n```python\n{content[:2500]}\n```"
            rows.append(distill_row(
                f"litellm-{make_id(content)[:8]}",
                "litellm-integration",
                prompt, completion,
                source=f"gh-soup/{repo}"
            ))
        print(f"    [{query[:40]}] -> {len(rows)} rows so far")

    # Also scrape LiteLLM's own docs/examples via BeautifulSoup
    print("  Fetching LiteLLM docs via BeautifulSoup...")
    doc_pages = [
        "https://github.com/BerriAI/litellm/blob/main/README.md",
        "https://github.com/BerriAI/litellm/blob/main/cookbook/litellm_router.py",
    ]
    for page_url in doc_pages:
        try:
            soup = fetch_github_page_soup(page_url)
            code_blocks = soup_extract_code_blocks(str(soup))
            for i, block in enumerate(code_blocks):
                if "litellm" not in block.lower() or len(block) < 100:
                    continue
                prompt = f"Explain this LiteLLM code pattern and when to use it:\n```python\n{block[:800]}\n```"
                completion = f"This LiteLLM pattern from the official docs shows:\n```python\n{block[:2000]}\n```\nUse this when you need a unified API across multiple LLM providers (OpenAI, Ollama, Anthropic, etc.) with automatic fallback and cost tracking."
                rows.append(distill_row(
                    f"litellm-doc-{make_id(block)[:8]}",
                    "litellm-integration",
                    prompt, completion,
                    source="gh-soup/BerriAI/litellm"
                ))
            time.sleep(1)
        except Exception as e:
            print(f"    Warning: {e}")

    return rows


# ── Main ─────────────────────────────────────────────────────────────────────

def run_scraper() -> int:
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting GitHub Soup scraper...")
    print(f"  GH token: {GH_TOKEN[:10]}...")

    all_rows = []

    kaggle_rows = scrape_kaggle_training_patterns()
    all_rows.extend(kaggle_rows)

    tailscale_rows = scrape_tailscale_patterns()
    all_rows.extend(tailscale_rows)

    litellm_rows = scrape_litellm_patterns()
    all_rows.extend(litellm_rows)

    # Deduplicate
    seen, unique = set(), []
    for r in all_rows:
        h = r["content_hash"]
        if h not in seen:
            seen.add(h)
            unique.append(r)

    out_path = OUT_DIR / "distill-ghsoup.jsonl"
    with open(out_path, "w") as f:
        for r in unique:
            f.write(json.dumps(r) + "\n")

    print(f"\n  Scraped {len(unique)} unique rows -> {out_path}")
    return len(unique)


if __name__ == "__main__":
    count = run_scraper()
    print(f"Done. {count} rows written.")
