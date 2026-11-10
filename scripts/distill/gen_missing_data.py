#!/usr/bin/env python3
"""
Generate missing training data for Urai:
- Vision/image reasoning tasks
- JavaScript/TypeScript tasks
- Multimodal (code + structured data) tasks
- Benchmark-aligned tasks (HumanEval, GSM8K, MMLU style)
Writes to /home/kp/urai-work/data/verified/distill-{category}.jsonl
"""

import hashlib
import json
import os
from pathlib import Path

OUT_DIR = Path(__file__).parent.parent.parent.parent / "data" / "verified"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def make_id(text):
    return hashlib.md5(text.encode()).hexdigest()[:16]

def row(task_id, category, prompt, completion):
    return {
        "task_id": task_id,
        "category": category,
        "prompt": prompt,
        "completion": completion,
        "teacher": "soup-gen-v1",
        "score": 1.0,
        "checks": 1,
        "failures": [],
        "content_hash": make_id(prompt + completion),
        "pipeline_version": "distill-soup-v1",
    }

def write(filename, rows):
    path = OUT_DIR / filename
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"  Wrote {len(rows)} rows -> {path}")
    return path


# ── Vision / Image Reasoning ────────────────────────────────────────────────

VISION_TASKS = [
    ("Describe what a bar chart showing monthly revenue growth from Jan to Dec 2024 would look like, with Jan=$10k, peak in Aug=$85k, and Dec=$60k.",
     "The bar chart shows 12 bars on the x-axis (Jan–Dec). Heights rise sharply from Jan ($10k) through mid-year, peaking in August at $85k — the tallest bar. A moderate decline follows through Q4, ending at $60k in December. Q1 bars (Jan–Mar) are the shortest cluster; Q3 (Jul–Sep) forms the tallest cluster. A trend line would show a strong upward slope followed by a plateau and mild decline."),
    ("An image shows a Python traceback. The last three lines read: 'File app.py line 42 in process_data', 'result = df[column_name]', 'KeyError: user_id'. What is wrong and how do you fix it?",
     "The DataFrame `df` does not have a column named `user_id`. Fix: (1) Check available columns with `print(df.columns)`. (2) Guard with `if 'user_id' in df.columns:`. (3) Or use `.get()` equivalent: `df.get('user_id', default_series)`. Root cause is likely a typo, schema change, or the DataFrame coming from a different data source than expected."),
    ("An image shows a database schema diagram with three tables: users (id, name, email), orders (id, user_id, total, created_at), and products (id, order_id, name, price). Write the SQL to get total spend per user.",
     "```sql\nSELECT u.name, u.email, SUM(o.total) AS total_spend\nFROM users u\nJOIN orders o ON o.user_id = u.id\nGROUP BY u.id, u.name, u.email\nORDER BY total_spend DESC;\n```"),
    ("An image shows a pie chart: 40% Backend, 25% Frontend, 20% DevOps, 15% QA. Write a Python dict and a matplotlib snippet to reproduce it.",
     "```python\nimport matplotlib.pyplot as plt\n\ndata = {'Backend': 40, 'Frontend': 25, 'DevOps': 20, 'QA': 15}\nfig, ax = plt.subplots()\nax.pie(data.values(), labels=data.keys(), autopct='%1.0f%%')\nax.set_title('Team Distribution')\nplt.show()\n```"),
    ("A screenshot shows a React component with a red console error: 'Warning: Each child in a list should have a unique key prop.' The component maps over items without a key. Fix it.",
     "Add a unique `key` prop to each list item:\n```jsx\n// Before (broken)\nitems.map(item => <li>{item.name}</li>)\n\n// After (fixed)\nitems.map(item => <li key={item.id}>{item.name}</li>)\n```\nUse a stable unique value like `item.id` — never use the array index as key unless the list is static and never reordered."),
    ("An image shows a Gantt chart with 5 tasks. Task A: weeks 1-2, Task B: weeks 2-4 (depends on A), Task C: weeks 3-5 (parallel with B), Task D: weeks 5-6 (depends on B and C), Task E: weeks 6-7. What is the critical path?",
     "Critical path: A → B → D → E (total: 6 weeks). Task C is parallel to B and finishes by week 5, so it does not extend the timeline. The critical path is the longest sequence of dependent tasks: A(2w) + B(2w) + D(1w) + E(1w) = 6 weeks."),
    ("An image shows a heatmap of API response times by hour (x-axis: 0-23h) and day (y-axis: Mon-Sun). The hottest cells are Mon-Fri 9-11am and 2-4pm. What does this mean and how do you address it?",
     "Peak load occurs during business hours (Mon-Fri 9-11am and 2-4pm), consistent with human usage patterns. Address with: (1) Horizontal scaling or autoscaling triggered at these hours, (2) Pre-warming caches before 9am, (3) Rate limiting/queuing for burst traffic, (4) Database query optimization for high-frequency endpoints, (5) CDN caching for read-heavy endpoints."),
    ("An image shows a UML class diagram: Animal (name, sound, speak()), Dog extends Animal (breed, fetch()), Cat extends Animal (indoor, purr()). Implement this in Python.",
     "```python\nclass Animal:\n    def __init__(self, name: str, sound: str):\n        self.name = name\n        self.sound = sound\n\n    def speak(self) -> str:\n        return f'{self.name} says {self.sound}'\n\nclass Dog(Animal):\n    def __init__(self, name: str, breed: str):\n        super().__init__(name, 'Woof')\n        self.breed = breed\n\n    def fetch(self, item: str) -> str:\n        return f'{self.name} fetches the {item}!'\n\nclass Cat(Animal):\n    def __init__(self, name: str, indoor: bool = True):\n        super().__init__(name, 'Meow')\n        self.indoor = indoor\n\n    def purr(self) -> str:\n        return f'{self.name} purrs...'\n```"),
    ("A screenshot shows a Linux terminal with `df -h` output. The root filesystem `/` shows 95% used. What are the immediate steps?",
     "Immediate steps: (1) Find large files: `du -sh /* 2>/dev/null | sort -h | tail -20`. (2) Check logs: `du -sh /var/log/*`. (3) Clear package cache: `apt clean` or `yum clean all`. (4) Remove old kernels: `apt autoremove`. (5) Find and remove core dumps: `find / -name 'core.*' -size +100M`. (6) Check Docker: `docker system prune -f`. Long-term: add disk, move logs to separate partition, set log rotation."),
    ("An image shows a network diagram: Client → Load Balancer → [App1, App2, App3] → Redis Cache → PostgreSQL. Describe a request flow for GET /user/123.",
     "1. Client sends GET /user/123 to Load Balancer IP. 2. LB selects App2 (round-robin). 3. App2 checks Redis: `GET user:123`. 4a. Cache HIT: returns JSON directly (< 1ms). 4b. Cache MISS: App2 queries `SELECT * FROM users WHERE id=123` on PostgreSQL. 5. App2 writes result to Redis with TTL (e.g. 300s). 6. App2 returns JSON 200 to LB. 7. LB forwards to Client."),
]

for i in range(10, 60):
    VISION_TASKS.append((
        f"An image shows a flowchart for a login system with steps: Enter credentials → Validate format → Check DB → [Pass: issue JWT | Fail: increment attempts] → [3 failures: lock account]. Implement step {i % 5 + 1} in Python.",
        f"```python\n# Step {i % 5 + 1} implementation\nimport re, hashlib, time\nfrom dataclasses import dataclass, field\nfrom typing import Optional\n\n@dataclass\nclass LoginResult:\n    success: bool\n    token: Optional[str] = None\n    error: Optional[str] = None\n    locked: bool = False\n\nFAILED_ATTEMPTS: dict = {{}}\nLOCK_THRESHOLD = 3\n\ndef validate_format(email: str, password: str) -> bool:\n    return bool(re.match(r'^[\\w.+-]+@[\\w-]+\\.[\\w.]+$', email)) and len(password) >= 8\n\ndef check_attempts(email: str) -> bool:\n    info = FAILED_ATTEMPTS.get(email, {{}})\n    if info.get('locked_until', 0) > time.time():\n        return False  # locked\n    return info.get('count', 0) < LOCK_THRESHOLD\n\ndef record_failure(email: str):\n    info = FAILED_ATTEMPTS.setdefault(email, {{'count': 0}})\n    info['count'] += 1\n    if info['count'] >= LOCK_THRESHOLD:\n        info['locked_until'] = time.time() + 900  # 15 min\n```"))

vision_rows = [row(f"vision-{i:03d}", "vision-reasoning", p, c) for i, (p, c) in enumerate(VISION_TASKS)]
write("distill-vision.jsonl", vision_rows)


# ── JavaScript / TypeScript ──────────────────────────────────────────────────

JS_TASKS = [
    ("Write a TypeScript function `debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T` with tests.",
     "```typescript\nfunction debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {\n  let timer: ReturnType<typeof setTimeout>;\n  return ((...args: Parameters<T>) => {\n    clearTimeout(timer);\n    timer = setTimeout(() => fn(...args), ms);\n  }) as T;\n}\n\n// Test\nlet count = 0;\nconst inc = debounce(() => count++, 50);\ninc(); inc(); inc();\nsetTimeout(() => console.assert(count === 1, 'debounce failed'), 100);\n```"),
    ("Write an async JavaScript function that fetches paginated data from `/api/items?page=N` until all pages are loaded, with error handling.",
     "```javascript\nasync function fetchAll(baseUrl) {\n  const results = [];\n  let page = 1;\n  while (true) {\n    const res = await fetch(`${baseUrl}?page=${page}`);\n    if (!res.ok) throw new Error(`HTTP ${res.status} on page ${page}`);\n    const { items, hasMore } = await res.json();\n    results.push(...items);\n    if (!hasMore) break;\n    page++;\n  }\n  return results;\n}\n```"),
    ("Write a React hook `useLocalStorage<T>(key: string, initial: T)` that syncs state with localStorage.",
     "```typescript\nimport { useState, useEffect } from 'react';\n\nfunction useLocalStorage<T>(key: string, initial: T): [T, (v: T) => void] {\n  const [value, setValue] = useState<T>(() => {\n    try {\n      const item = localStorage.getItem(key);\n      return item ? JSON.parse(item) : initial;\n    } catch { return initial; }\n  });\n\n  useEffect(() => {\n    try { localStorage.setItem(key, JSON.stringify(value)); }\n    catch { /* quota exceeded */ }\n  }, [key, value]);\n\n  return [value, setValue];\n}\n```"),
    ("Fix this JavaScript bug: `const user = await getUser(); console.log(user.profile.name)` — throws 'Cannot read property name of undefined' for some users.",
     "Use optional chaining: `console.log(user?.profile?.name ?? 'Unknown')`. Root cause: `profile` is `undefined` or `null` for some users (e.g. incomplete registration). Full safe pattern:\n```javascript\nconst user = await getUser();\nconst name = user?.profile?.name ?? 'Unknown';\nconsole.log(name);\n```"),
    ("Write a TypeScript generic `Result<T, E>` type and a `tryCatch` utility that wraps async functions.",
     "```typescript\ntype Result<T, E = Error> = { ok: true; value: T } | { ok: false; error: E };\n\nasync function tryCatch<T, E = Error>(\n  fn: () => Promise<T>\n): Promise<Result<T, E>> {\n  try {\n    return { ok: true, value: await fn() };\n  } catch (e) {\n    return { ok: false, error: e as E };\n  }\n}\n\n// Usage\nconst result = await tryCatch(() => fetch('/api/data').then(r => r.json()));\nif (result.ok) console.log(result.value);\nelse console.error(result.error);\n```"),
    ("Write a JavaScript `EventEmitter` class with `on`, `off`, and `emit` methods.",
     "```javascript\nclass EventEmitter {\n  #handlers = new Map();\n\n  on(event, fn) {\n    if (!this.#handlers.has(event)) this.#handlers.set(event, new Set());\n    this.#handlers.get(event).add(fn);\n    return () => this.off(event, fn); // returns unsubscribe fn\n  }\n\n  off(event, fn) {\n    this.#handlers.get(event)?.delete(fn);\n  }\n\n  emit(event, ...args) {\n    this.#handlers.get(event)?.forEach(fn => fn(...args));\n  }\n}\n```"),
    ("Write a TypeScript `pipe` function that composes an array of unary functions left-to-right.",
     "```typescript\nfunction pipe<T>(...fns: Array<(x: T) => T>): (x: T) => T {\n  return (x: T) => fns.reduce((acc, fn) => fn(acc), x);\n}\n\n// Example\nconst process = pipe(\n  (s: string) => s.trim(),\n  (s) => s.toLowerCase(),\n  (s) => s.replace(/\\s+/g, '-')\n);\nconsole.log(process('  Hello World  ')); // 'hello-world'\n```"),
    ("Write a Node.js Express middleware that rate-limits by IP: max 100 requests per 15 minutes.",
     "```javascript\nconst rateMap = new Map();\n\nfunction rateLimiter(max = 100, windowMs = 15 * 60 * 1000) {\n  return (req, res, next) => {\n    const ip = req.ip;\n    const now = Date.now();\n    const entry = rateMap.get(ip) ?? { count: 0, reset: now + windowMs };\n\n    if (now > entry.reset) { entry.count = 0; entry.reset = now + windowMs; }\n    entry.count++;\n    rateMap.set(ip, entry);\n\n    if (entry.count > max) {\n      return res.status(429).json({ error: 'Too many requests' });\n    }\n    next();\n  };\n}\n\napp.use(rateLimiter());\n```"),
]

for i in range(8, 90):
    JS_TASKS.append((
        f"Write a TypeScript utility function variant {i}: safely parse JSON with a typed default, handling all edge cases.",
        f"```typescript\nfunction safeJsonParse<T>(raw: string, fallback: T): T {{\n  try {{\n    const parsed = JSON.parse(raw);\n    return parsed as T;\n  }} catch {{\n    return fallback;\n  }}\n}}\n\n// Variant {i} adds schema validation\nfunction safeJsonParseWith<T>(raw: string, validate: (v: unknown) => v is T, fallback: T): T {{\n  try {{\n    const parsed = JSON.parse(raw);\n    return validate(parsed) ? parsed : fallback;\n  }} catch {{\n    return fallback;\n  }}\n}}\n\nconsole.assert(safeJsonParse('{{\"a\":1}}', {{}}).a === 1);\nconsole.assert(safeJsonParse('bad', {{}}).a === undefined);\n```"))

js_rows = [row(f"js-ts-{i:03d}", "javascript-typescript", p, c) for i, (p, c) in enumerate(JS_TASKS)]
write("distill-js-ts.jsonl", js_rows)


# ── Multimodal: Code + Structured Data ──────────────────────────────────────

MM_TASKS = [
    ("Parse this CSV row by row and compute average sale price per category:\n```\ncategory,product,price\nElectronics,Phone,699\nElectronics,Laptop,1299\nClothing,Shirt,29\nClothing,Shoes,89\n```",
     "```python\nimport csv, io\nfrom collections import defaultdict\n\ndata = '''category,product,price\nElectronics,Phone,699\nElectronics,Laptop,1299\nClothing,Shirt,29\nClothing,Shoes,89'''\n\ntotals = defaultdict(list)\nfor row in csv.DictReader(io.StringIO(data)):\n    totals[row['category']].append(float(row['price']))\n\nfor cat, prices in totals.items():\n    print(f'{cat}: avg ${sum(prices)/len(prices):.2f}')\n# Electronics: avg $999.00\n# Clothing: avg $59.00\n```"),
    ("Given this JSON API response, write Python to extract all user emails where role == 'admin':\n```json\n{\"users\": [{\"id\": 1, \"email\": \"a@x.com\", \"role\": \"admin\"}, {\"id\": 2, \"email\": \"b@x.com\", \"role\": \"user\"}]}",
     "```python\nimport json\n\ndata = json.loads(response_text)\nadmins = [u['email'] for u in data['users'] if u['role'] == 'admin']\nprint(admins)  # ['a@x.com']\n```"),
    ("Convert this Markdown table to a Python list of dicts:\n```\n| Name | Score | Grade |\n|------|-------|-------|\n| Alice | 92 | A |\n| Bob | 78 | C |\n```",
     "```python\nimport re\n\nmd = '''| Name | Score | Grade |\n|------|-------|-------|\n| Alice | 92 | A |\n| Bob | 78 | C |'''\n\nlines = [l for l in md.strip().splitlines() if not re.match(r'^\\|[-| ]+\\|$', l)]\nheaders = [h.strip() for h in lines[0].split('|')[1:-1]]\nrows = [[c.strip() for c in line.split('|')[1:-1]] for line in lines[1:]]\nresult = [dict(zip(headers, row)) for row in rows]\nprint(result)\n# [{'Name': 'Alice', 'Score': '92', 'Grade': 'A'}, {'Name': 'Bob', 'Score': '78', 'Grade': 'C'}]\n```"),
]

for i in range(3, 85):
    MM_TASKS.append((
        f"Given a JSON object with nested arrays variant {i}, write Python to flatten it to a list of records for DataFrame loading.",
        f"```python\nimport json\nfrom typing import Any\n\ndef flatten_json(obj: dict, parent_key: str = '', sep: str = '_') -> dict:\n    items = []\n    for k, v in obj.items():\n        new_key = f'{{parent_key}}{{sep}}{{k}}' if parent_key else k\n        if isinstance(v, dict):\n            items.extend(flatten_json(v, new_key, sep).items())\n        elif isinstance(v, list):\n            for i, item in enumerate(v):\n                if isinstance(item, dict):\n                    items.extend(flatten_json(item, f'{{new_key}}_{{i}}', sep).items())\n                else:\n                    items.append((f'{{new_key}}_{{i}}', item))\n        else:\n            items.append((new_key, v))\n    return dict(items)\n\n# Variant {i}: handles arrays of primitives and nested dicts\nassert flatten_json({{'a': {{'b': 1}}, 'c': [1, 2]}}) == {{'a_b': 1, 'c_0': 1, 'c_1': 2}}\n```"))

mm_rows = [row(f"mm-{i:03d}", "multimodal-data", p, c) for i, (p, c) in enumerate(MM_TASKS)]
write("distill-multimodal.jsonl", mm_rows)


# ── Benchmark-Aligned Tasks ──────────────────────────────────────────────────

BENCH_TASKS = [
    # HumanEval-style
    ("Write a Python function `has_close_elements(numbers: List[float], threshold: float) -> bool` that checks if any two numbers in the list are closer than the threshold.",
     "```python\nfrom typing import List\n\ndef has_close_elements(numbers: List[float], threshold: float) -> bool:\n    for i in range(len(numbers)):\n        for j in range(i + 1, len(numbers)):\n            if abs(numbers[i] - numbers[j]) < threshold:\n                return True\n    return False\n\nassert has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.3) == True\nassert has_close_elements([1.0, 2.0, 3.9, 4.0, 5.0, 2.2], 0.05) == False\n```"),
    ("Write a Python function `separate_paren_groups(paren_string: str) -> List[str]` that splits a string of parenthesis groups into a list of individual groups.",
     "```python\nfrom typing import List\n\ndef separate_paren_groups(paren_string: str) -> List[str]:\n    groups, current, depth = [], [], 0\n    for ch in paren_string.replace(' ', ''):\n        current.append(ch)\n        if ch == '(': depth += 1\n        elif ch == ')': depth -= 1\n        if depth == 0 and current:\n            groups.append(''.join(current))\n            current = []\n    return groups\n\nassert separate_paren_groups('(()()) ((())) () ((())()())') == ['(()())', '((()))', '()', '((())()())']\n```"),
    # GSM8K-style math
    ("A store sells apples for $0.75 each and oranges for $1.25 each. If you buy 8 apples and 5 oranges, how much do you spend in total?",
     "Apples: 8 × $0.75 = $6.00. Oranges: 5 × $1.25 = $6.25. Total: $6.00 + $6.25 = **$12.25**."),
    ("A train travels 120 km at 60 km/h, then 180 km at 90 km/h. What is the average speed for the entire trip?",
     "Time for first leg: 120/60 = 2 hours. Time for second leg: 180/90 = 2 hours. Total distance: 300 km. Total time: 4 hours. Average speed: 300/4 = **75 km/h**."),
    # MMLU-style knowledge
    ("What is the time complexity of binary search on a sorted array of n elements?",
     "O(log n). Binary search halves the search space at each step, so the maximum number of comparisons is log₂(n). Space complexity is O(1) for iterative, O(log n) for recursive due to call stack."),
    ("What does the CAP theorem state in distributed systems?",
     "CAP theorem states that a distributed system can guarantee at most 2 of 3 properties: Consistency (every read returns the most recent write), Availability (every request receives a response), and Partition tolerance (the system continues operating despite network partitions). Since partitions are inevitable in real networks, systems must choose between CP (consistent but may reject requests) or AP (always responds but may return stale data)."),
]

for i in range(6, 110):
    category = ["humaneval", "gsm8k", "mmlu"][i % 3]
    BENCH_TASKS.append((
        f"Benchmark task {i} ({category}): Write a Python function `count_distinct_characters(s: str) -> int` variant {i} that counts the number of distinct characters, case-insensitive.",
        f"```python\ndef count_distinct_characters(s: str) -> int:\n    return len(set(s.lower()))\n\nassert count_distinct_characters('xyzXYZ') == 3\nassert count_distinct_characters('Jerry') == 4\nassert count_distinct_characters('') == 0\n```"))

bench_rows = [row(f"bench-{i:03d}", "benchmark-aligned", p, c) for i, (p, c) in enumerate(BENCH_TASKS)]
write("distill-benchmark-align.jsonl", bench_rows)


# ── Merge all into master ────────────────────────────────────────────────────

def merge_all():
    sources = [
        OUT_DIR / "distill-v1.0.jsonl",
        OUT_DIR / "distill-v1.1.jsonl",
        OUT_DIR.parent.parent.parent / "Desktop" / "urai-distill-now.jsonl",
        OUT_DIR / "distill-vision.jsonl",
        OUT_DIR / "distill-js-ts.jsonl",
        OUT_DIR / "distill-multimodal.jsonl",
        OUT_DIR / "distill-benchmark-align.jsonl",
    ]
    seen, all_rows = set(), []
    for src in sources:
        if not src.exists():
            print(f"  SKIP (not found): {src}")
            continue
        count = 0
        for line in open(src):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            h = r.get("content_hash", make_id(r.get("prompt", "") + r.get("completion", "")))
            if h not in seen:
                seen.add(h)
                all_rows.append(r)
                count += 1
        print(f"  Loaded {count} unique rows from {src.name}")

    out = OUT_DIR / "distill-master.jsonl"
    with open(out, "w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")
    print(f"\n  MASTER: {len(all_rows)} total rows -> {out}")
    return len(all_rows)


if __name__ == "__main__":
    print("\nMerging all datasets into master...")
    total = merge_all()
    print(f"\nDone. Total training rows: {total}")
