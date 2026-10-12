# Dataset Pipeline (Phase 2 prototype — working, offline)

Status: prototype runs end-to-end TODAY with zero API keys.
Proven run: `python3 scripts/distill/run_distill.py` on
`data/raw_tasks/sample_tasks.jsonl` → **10 tasks → 5 kept, 4 rejected,
1 duplicate caught** (report: `eval/reports/distill-v0.1-summary.json`).

## 1. Pipeline stages (implemented)

```
data/raw_tasks/*.jsonl          task records: {id, category, prompt, reference_good?}
  → scripts/distill/teacher_client.py    Teacher interface.
        MockTeacher (offline, deterministic) | OpenAICompatibleTeacher
        (any OpenAI-chat endpoint via TEACHER_BASE_URL/KEY/MODEL env)
  → scripts/distill/verifier.py          score 0..1 + failure tags:
        python blocks → compile() | json blocks → json.loads
        whole text → secret scan + banned-pattern scan
        ANY leak tag (api key, password, token, private key, /home/…)
        → hard score 0.0
  → scripts/distill/filter.py            threshold (default 0.8) + dedup
        on normalized-content sha256 (provenance kept)
  → data/verified/distill-*.jsonl        records carry score, failures,
        content_hash, teacher id, pipeline_version (reproducible)
```

## 2. Known limitation (honest)

Text-only tasks (debugging checklists, git recipes) score 0.5 "neutral" —
nothing executable to verify. They are currently rejected, which is
correct-but-lossy. Fix (planned): rubric-based LLM-judge as a SECOND
signal, never overriding a failed execution check. Execution stays the
gatekeeper for code.

## 3. Rejection catalogue (mission §7, enforced in `verifier.py`)

failing code · malformed JSON · unsafe calls (`eval(`) · leaked secrets ·
private paths · fabricated benchmark claims · model-slop phrasing.
Extend the pattern lists, don't weaken them.

## 4. Teacher strategy with NO keys yet (current state)

Order of attack, cheapest-first:

1. **Local draft teacher**: the Qwen2.5-0.5B Q4 now in `model/base/` —
   weak, but free and unlimited. Useful for pipeline shakedown + negative
   examples, NOT for quality data.
2. **Free tiers (verify current terms at signup, use via
   `OpenAICompatibleTeacher`)**: Google AI Studio (Gemini free tier),
   OpenRouter `:free` models, Groq free tier. Good for hundreds–thousands
   of generations at zero cost. Watch rate limits + data-use terms.
3. **Paid teachers, metered**: strongest coding model for code tasks,
   strongest reasoning model for reasoning tasks (mission §3 matrix).
   Spend only on tasks that passed pilot quality bars on free tiers.
4. **License hygiene**: only use teacher outputs as each provider's terms
   allow; never distill a model whose license forbids it; record teacher
   id + version on EVERY record (already in schema).

## 5. Data governance (mission §26, enforced)

- Secret scan runs BEFORE anything is written to `data/verified/`.
- Never include: API keys, passwords, wallet secrets, production DB dumps,
  private user data, proprietary credentials, real customer code.
- Sample tasks are anonymized patterns (ledger inserts, bisect recipes),
  not production code.

## 6. Next steps (Phase 2 remainder)

- [ ] LLM-judge second signal for text-only tasks
- [ ] pytest hook: run generated code against real test files, use
      pass/fail as score (mission §8)
- [ ] preference-pair miner: GOOD vs BAD from kept/rejected pairs (§9)
- [ ] scale raw tasks to 200+ across all 8 dataset categories (§6)
- [ ] record teacher matrix once free-tier keys exist (§3)
