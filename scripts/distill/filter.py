#!/usr/bin/env python3
"""Filter + dedup stage: score -> threshold -> dedup -> structured record.

Rejects (mission §7): failing code, malformed JSON, unsafe calls, leaked
secrets, fabricated claims. Dups detected on normalized content hash —
the same correct answer from two teachers is stored once (provenance kept).
"""

import hashlib
import re

PASS_THRESHOLD = 0.8


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize(content).encode()).hexdigest()[:16]


def build_record(task: dict, teacher_out, verdict: dict) -> dict:
    return {
        "task_id": task["id"],
        "category": task.get("category", "general"),
        "prompt": task["prompt"],
        "completion": teacher_out.content,
        "teacher": teacher_out.model,
        "score": verdict["score"],
        "checks": verdict["checks"],
        "failures": verdict["failures"],
        "content_hash": content_hash(teacher_out.content),
        "pipeline_version": "distill-v0.1",
    }


def filter_batch(scored: list, threshold: float = PASS_THRESHOLD) -> dict:
    seen = set()
    kept, rejected, dupes = [], [], []
    for item in scored:
        rec, verdict_ok = item["record"], item["verdict"]["score"] >= threshold
        if not verdict_ok:
            rejected.append(item)
            continue
        if rec["content_hash"] in seen:
            dupes.append(item)
            continue
        seen.add(rec["content_hash"])
        kept.append(item)
    return {"kept": kept, "rejected": rejected, "dupes": dupes}
