"""
jev/router.py — Intent classifier and backend router for Urai.

Upgraded with a TF-IDF neural intent classifier. The TF-IDF layer runs first;
if its confidence score exceeds 0.4 the result is used directly, otherwise the
legacy keyword-regex path is the fallback.

New symbols:  _tfidf_classify, _learn
Preserved:    pick_backend, route, TIERS (unchanged)
"""
from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# TF-IDF classifier — stdlib only
# ---------------------------------------------------------------------------

_LEARN_FILE = Path(os.environ.get("URAI_DATA_DIR", "data")) / "router_examples.jsonl"

# 40 hardcoded seed examples (10 per class)
_SEED_EXAMPLES: List[Tuple[str, str]] = [
    # casual
    ("hey how are you doing today", "casual"),
    ("what is the weather like", "casual"),
    ("tell me a joke please", "casual"),
    ("who won the world cup", "casual"),
    ("what time is it", "casual"),
    ("good morning how is everything", "casual"),
    ("can you recommend a movie", "casual"),
    ("what should I eat for dinner", "casual"),
    ("do you like music", "casual"),
    ("nice to meet you", "casual"),
    # coder
    ("write a python function to sort a list", "coder"),
    ("fix the bug in my javascript code", "coder"),
    ("how do I implement a binary search tree", "coder"),
    ("explain this regex pattern", "coder"),
    ("what is the time complexity of quicksort", "coder"),
    ("help me refactor this class", "coder"),
    ("debug this stack trace", "coder"),
    ("write unit tests for my module", "coder"),
    ("how do I parse JSON in rust", "coder"),
    ("generate a dockerfile for a flask app", "coder"),
    # browser
    ("search the web for the latest news", "browser"),
    ("find the homepage of openai", "browser"),
    ("look up the documentation for numpy", "browser"),
    ("visit the github repository for react", "browser"),
    ("what is on the front page of hacker news", "browser"),
    ("browse to the python docs", "browser"),
    ("check the latest pytorch release notes", "browser"),
    ("fetch the content from this url", "browser"),
    ("go to wikipedia and find information about mars", "browser"),
    ("open the aws console documentation", "browser"),
    # planner
    ("create a project plan for a mobile app", "planner"),
    ("outline the steps to build a microservice", "planner"),
    ("what is the roadmap for this feature", "planner"),
    ("help me design the architecture for a chat system", "planner"),
    ("plan a sprint for the next two weeks", "planner"),
    ("break down this epic into tasks", "planner"),
    ("what should be the milestones for this project", "planner"),
    ("design a schema for a user database", "planner"),
    ("how should I structure a rest api", "planner"),
    ("propose a system design for real time notifications", "planner"),
]


def _tokenise(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    return re.findall(r"[a-z0-9]+", text.lower())


class _TfIdfClassifier:
    """Minimal multi-class TF-IDF nearest-centroid classifier."""

    def __init__(self, examples: List[Tuple[str, str]]) -> None:
        self._labels: List[str] = sorted({label for _, label in examples})
        # Build vocabulary and DF counts.
        all_docs: List[List[str]] = [_tokenise(t) for t, _ in examples]
        vocab: Dict[str, int] = {}
        df: Dict[str, int] = Counter()
        for tokens in all_docs:
            for tok in set(tokens):
                df[tok] += 1
                if tok not in vocab:
                    vocab[tok] = len(vocab)
        self._vocab = vocab
        n_docs = len(examples)
        self._idf: Dict[str, float] = {
            tok: math.log((n_docs + 1) / (cnt + 1)) + 1.0
            for tok, cnt in df.items()
        }
        # Build per-label centroid TF-IDF vectors.
        label_vecs: Dict[str, List[float]] = {lbl: [0.0] * len(vocab) for lbl in self._labels}
        label_counts: Dict[str, int] = Counter()
        for (text, label), tokens in zip(examples, all_docs):
            tf = Counter(tokens)
            max_tf = max(tf.values()) if tf else 1
            for tok, cnt in tf.items():
                if tok in vocab:
                    idx = vocab[tok]
                    label_vecs[label][idx] += (cnt / max_tf) * self._idf.get(tok, 1.0)
            label_counts[label] += 1
        # Average to centroid and normalise.
        self._centroids: Dict[str, List[float]] = {}
        for lbl in self._labels:
            vec = [v / max(label_counts[lbl], 1) for v in label_vecs[lbl]]
            self._centroids[lbl] = _l2_normalise(vec)

    def predict(self, text: str) -> Tuple[str, float]:
        """Return (label, score) where score in [0,1] is cosine similarity."""
        tokens = _tokenise(text)
        tf = Counter(tokens)
        max_tf = max(tf.values()) if tf else 1
        vec = [0.0] * len(self._vocab)
        for tok, cnt in tf.items():
            if tok in self._vocab:
                idx = self._vocab[tok]
                vec[idx] = (cnt / max_tf) * self._idf.get(tok, 1.0)
        vec = _l2_normalise(vec)
        best_lbl, best_score = self._labels[0], -1.0
        for lbl in self._labels:
            centroid = self._centroids[lbl]
            score = sum(a * b for a, b in zip(vec, centroid))
            if score > best_score:
                best_score = score
                best_lbl = lbl
        return best_lbl, max(0.0, best_score)


def _l2_normalise(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _load_learned_examples() -> List[Tuple[str, str]]:
    if not _LEARN_FILE.exists():
        return []
    rows: List[Tuple[str, str]] = []
    with _LEARN_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                rows.append((obj["prompt"], obj["label"]))
            except (json.JSONDecodeError, KeyError):
                pass
    return rows


_classifier: Optional[_TfIdfClassifier] = None


def _get_classifier() -> _TfIdfClassifier:
    global _classifier
    if _classifier is None:
        extra = _load_learned_examples()
        _classifier = _TfIdfClassifier(_SEED_EXAMPLES + extra)
    return _classifier


def _tfidf_classify(prompt: str) -> Dict[str, Any]:
    """
    Classify *prompt* using TF-IDF nearest-centroid.

    Returns
    -------
    {"agent": str, "score": float, "method": "tfidf"}
    """
    clf = _get_classifier()
    label, score = clf.predict(prompt)
    return {"agent": label, "score": score, "method": "tfidf"}


def _learn(prompt: str, label: str) -> None:
    """
    Append *(prompt, label)* to data/router_examples.jsonl for continuous
    improvement. Resets the cached classifier so it rebuilds on next call.
    """
    global _classifier
    _LEARN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _LEARN_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"prompt": prompt, "label": label}, ensure_ascii=False) + "\n")
    _classifier = None  # reset so classifier rebuilds with new data


# ---------------------------------------------------------------------------
# Legacy keyword-regex classifier (preserved unchanged)
# ---------------------------------------------------------------------------

_KEYWORD_PATTERNS: Dict[str, re.Pattern] = {
    "coder": re.compile(
        r"\b(code|function|bug|debug|error|implement|class|script|python|javascript"
        r"|rust|golang|typescript|refactor|unittest|test|dockerfile|api)\b",
        re.IGNORECASE,
    ),
    "browser": re.compile(
        r"\b(search|browse|url|website|web|fetch|http|find online|look up"
        r"|documentation|github|docs|homepage|visit)\b",
        re.IGNORECASE,
    ),
    "planner": re.compile(
        r"\b(plan|roadmap|milestone|sprint|architecture|design|schema|structure"
        r"|outline|breakdown|epic|task|feature|proposal)\b",
        re.IGNORECASE,
    ),
}


def _keyword_classify(prompt: str) -> Optional[str]:
    """Return label from keyword regex, or None if no pattern matches."""
    for label, pattern in _KEYWORD_PATTERNS.items():
        if pattern.search(prompt):
            return label
    return None


def classify(prompt: str) -> Dict[str, Any]:
    """
    Classify *prompt* into an agent label.

    Strategy:
      1. TF-IDF classifier — if score > 0.4, use it.
      2. Keyword regex fallback.
      3. Default to "casual".

    Returns
    -------
    {"agent": str, "score": float, "method": "tfidf" | "keyword" | "default"}
    """
    result = _tfidf_classify(prompt)
    if result["score"] > 0.4:
        return result

    kw_label = _keyword_classify(prompt)
    if kw_label:
        return {"agent": kw_label, "score": 0.5, "method": "keyword"}

    return {"agent": "casual", "score": 1.0, "method": "default"}


# ---------------------------------------------------------------------------
# TIERS and backend routing (preserved from original)
# ---------------------------------------------------------------------------

TIERS: Dict[str, List[str]] = {
    "fast": ["qwen3-coder-next", "deepseek-3.2"],
    "balanced": ["qwen3-coder-next", "minimax-m2.5"],
    "quality": ["minimax-m2.5", "glm-5"],
}

_AGENT_TIER: Dict[str, str] = {
    "casual": "fast",
    "coder": "balanced",
    "browser": "balanced",
    "planner": "quality",
}


def pick_backend(agent_label: str, tier_override: Optional[str] = None) -> str:
    """
    Return the preferred model id for *agent_label*.

    Parameters
    ----------
    agent_label   : label returned by classify()
    tier_override : force a specific tier ("fast" | "balanced" | "quality")
    """
    tier = tier_override or _AGENT_TIER.get(agent_label, "balanced")
    candidates = TIERS.get(tier, TIERS["balanced"])
    return candidates[0]


def route(
    prompt: str,
    tier_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Full routing: classify *prompt* then pick a backend model.

    Returns
    -------
    {"agent": str, "model": str, "score": float, "method": str}
    """
    clf_result = classify(prompt)
    model = pick_backend(clf_result["agent"], tier_override=tier_override)
    return {
        "agent": clf_result["agent"],
        "model": model,
        "score": clf_result["score"],
        "method": clf_result["method"],
    }
