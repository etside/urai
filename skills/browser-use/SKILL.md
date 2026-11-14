---
name: browser-use
description: "Direct browser control via Playwright/CDP for web interaction: automation, scraping, testing, screenshots, and site/app work. Use Urai's built-in browser tool (urai_browser) for tasks needing click, type, navigate, JS rendering, or logged-in sessions. Falls back to plain HTTP fetch for public pages."
source: https://github.com/browser-use/browser-use
---

# Browser Use (Urai)

Urai has a built-in Playwright browser available via the `browser_run` tool.

## When to Use

Use `browser_run` when:
- Task needs interaction (click, type, navigate, fill forms)
- Page requires JS rendering or login session
- Bot-protected pages (Urai uses human-like delays)
- Screenshots or visual verification needed

Do NOT use the browser for plain public information — use `web_search` or `web_fetch` instead. Browser is slower and costs more context.

## Urai Browser Tool

```json
{"tool": "browser_run", "args": {"task": "go to example.com and click the login button", "screenshot": true}}
```

Returns: `{ok, result, screenshot_path, steps_taken}`

## Safety Rules

- Never submit forms with real payment data without explicit user approval
- Always show screenshot result to user before confirming success
- Urai's browser uses human-like pauses to avoid bot detection
- External actions (buy, send, delete) require approval queue

## Advanced: browser-use Python Library

For complex automation, install browser-use:
```bash
pip install browser-use playwright
playwright install chromium
```

Then use via Urai's code executor:
```python
from browser_use import Agent, Browser
browser = Browser()
agent = Agent(task="find the cheapest flight from NYC to LA", browser=browser)
result = agent.run()
```

## Best Practices (from browser-use/browser-use)

- First navigation: use `new_tab(url)` not repeated navigations
- Find elements via accessibility tree before screenshots
- After navigation: wait for load before interacting
- Login walls: stop and ask user before proceeding
- Keep one tab per task; close when done
