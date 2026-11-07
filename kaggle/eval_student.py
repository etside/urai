#!/usr/bin/env python3
"""Gate: distilled student vs teacher on HELD-OUT Urai tasks.

Usage:
    python3 kaggle/eval_student.py \
        --student-base http://127.0.0.1:11434 \
        --student-model urai-qwen3-1.7b \
        --teacher-base https://52-66-18-45.sslip.io \
        --master-key $URAI_MASTER_KEY \
        --tasks data/raw_tasks/sample_tasks.jsonl \
        --out data/finetune/muse-spark-open/eval.json

Queries both, scores answers with a simple rubric check (presence of
expected keywords + non-empty + reasonable length), and prints a win rate.
The student "wins" when its score >= teacher's on >= 70% of tasks.
"""
import argparse, json, statistics, sys, time, urllib.request
from pathlib import Path

def ask(base, model, prompt, key=""):
    body = json.dumps({"model": model, "messages": [
        {"role": "user", "content": prompt}], "max_tokens": 512}).encode()
    req = urllib.request.Request(f"{base.rstrip('/')}/v1/chat/completions",
        body, {"Content-Type": "application/json",
               **({"Authorization": f"Bearer {key}"} if key else {})})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.load(r)
        content = d["choices"][0]["message"]["content"]
        return content, time.time() - t0
    except Exception as e:
        return f"[error] {e}", time.time() - t0

def score(ans, rubric_terms):
    if not ans or ans.startswith("[error]"):
        return 0.0
    low = ans.lower()
    hits = sum(1 for t in rubric_terms if t.lower() in low)
    return hits / max(len(rubric_terms), 1)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--student-base", default="http://127.0.0.1:11434")
    ap.add_argument("--student-model", default="urai-qwen3-1.7b")
    ap.add_argument("--teacher-base", default="https://52-66-18-45.sslip.io")
    ap.add_argument("--master-key", default="")
    ap.add_argument("--tasks", default="data/raw_tasks/sample_tasks.jsonl")
    ap.add_argument("--out", default="data/finetune/muse-spark-open/eval.json")
    a = ap.parse_args()

    tasks = [json.loads(l) for l in Path(a.tasks).read_text().splitlines() if l.strip()]
    results = []
    wins = losses = draws = 0
    for t in tasks[:20]:
        prompt = t.get("prompt", "")
        terms = t.get("judge_rubric_terms") or []
        if not terms and t.get("judge_rubric"):
            rubric = t["judge_rubric"]
            terms = [w.strip("* ").split()[0] for w in rubric.replace("\n", " ").split() if len(w) > 3][:6]
        s, ts = ask(a.student_base, a.student_model, prompt)
        t_, tt = ask(a.teacher_base, "urai", prompt, a.master_key)
        s_score, t_score = score(s, terms), score(t_, terms)
        if s_score > t_score: wins += 1
        elif s_score < t_score: losses += 1
        else: draws += 1
        results.append({"prompt": prompt[:80], "student": s_score,
                        "teacher": t_score, "t_student": round(ts, 1),
                        "t_teacher": round(tt, 1)})
        print(f"[{len(results)}/{len(tasks)}] student {s_score:.2f} vs teacher {t_score:.2f} "
              f"({ts:.0f}s vs {tt:.0f}s)")
    n = max(wins + losses + draws, 1)
    gate = wins / n
    Path(a.out).write_text(json.dumps({"wins": wins, "losses": losses,
        "draws": draws, "win_rate": gate, "results": results}, indent=1))
    print(f"wins {wins} losses {losses} draws {draws} win_rate {gate:.0%}")
    print("GATE:", "PASS (>=70%)" if gate >= 0.7 else "FAIL")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
