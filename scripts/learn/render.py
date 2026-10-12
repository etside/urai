#!/usr/bin/env python3
"""Render JS-heavy pages with headless Chromium (Playwright) -> clean text.

For pages that keyless web_fetch can't read (JS-rendered docs, dashboards).
Runs wherever Playwright + Chromium exist (VPS: installed via
`pip install playwright && python -m playwright install --with-deps chromium`).

    python3 scripts/learn/render.py --urls urls.txt --out rendered.jsonl
    python3 scripts/learn/ingest.py --topic x --urls rendered.txt ...

Output .jsonl rows: {"url", "title", "text"}. Feed through ingest by
writing URLs that need rendering to a file, or import render_page().
"""

import argparse
import json
import re
import sys


def render_page(url: str, timeout_ms: int = 45000) -> dict:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        try:
            page = browser.new_page(user_agent="urai-learn/1.0")
            page.goto(url, wait_until="domcontentloaded",
                      timeout=timeout_ms)
            try:
                page.wait_for_timeout(3000)
            except Exception:
                pass
            title = page.title()
            text = page.evaluate(
                "() => document.body ? document.body.innerText : ''")
        finally:
            browser.close()
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return {"url": url, "title": title, "text": text[:30000]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    urls = [ln.strip() for ln in open(args.urls)
            if ln.strip() and not ln.startswith("#")]
    n = 0
    with open(args.out, "w") as f:
        for url in urls:
            try:
                r = render_page(url)
                if not r["text"]:
                    print(f"SKIP empty: {url}")
                    continue
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
                print(f"+ {r['title'][:60]} ({len(r['text'])} chars)")
            except Exception as e:
                print(f"SKIP {url}: {str(e)[:100]}")
    print(f"rendered {n} pages -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
