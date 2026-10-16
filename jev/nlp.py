#!/usr/bin/env python3
"""NLP request understanding — the first stage of every request.

`analyze(text, history=None)` is deterministic and stdlib-only so it runs on a
CPU VPS and in CI with no model or GPU. It extracts:

    language, sentiment{label,score,confidence}, emotion, intensity, urgency,
    intent, entities[], topics[], complexity, redflags[]

Optional model upgrade: if the embeddings endpoint is available the caller can
blend embedding-based topic proximity (see jev/retrieval.py), but the contract
below never depends on it. No network calls here.
"""

import re
import unicodedata

# ------------------------------------------------------------------ language
_SCRIPTS = [
    ("bn", r"[\u0980-\u09FF]"),
    ("hi", r"[\u0900-\u097F]"),
    ("ar", r"[\u0600-\u06FF]"),
    ("ru", r"[\u0400-\u04FF]"),
    ("ko", r"[\uAC00-\uD7AF]"),
    ("ja", r"[\u3040-\u30FF]"),
    ("zh", r"[\u4E00-\u9FFF]"),
]
_STOP = {
    "en": {"the", "and", "is", "are", "to", "of", "in", "you", "for", "with", "this", "that", "how", "what"},
    "es": {"el", "la", "los", "las", "de", "que", "y", "en", "un", "una", "por", "con", "como"},
    "fr": {"le", "la", "les", "des", "de", "et", "est", "un", "une", "pour", "avec", "que"},
    "de": {"der", "die", "das", "und", "ist", "ein", "eine", "mit", "fur", "für", "nicht", "wie"},
    "pt": {"o", "a", "os", "as", "de", "que", "e", "em", "um", "uma", "para", "com"},
    "it": {"il", "la", "i", "le", "di", "che", "e", "un", "una", "per", "con", "come"},
}


def detect_language(text: str) -> str:
    t = text or ""
    for code, pat in _SCRIPTS:
        if re.search(pat, t):
            return code
    words = set(re.findall(r"[a-zA-ZÀ-ÿ']+", t.lower()))
    if not words:
        return "en"
    best, best_hits = "en", 0
    for code, stops in _STOP.items():
        hits = len(words & stops)
        if hits > best_hits:
            best, best_hits = code, hits
    return best


# ------------------------------------------------------------------ sentiment
_POS = {
    "good": 1.0, "great": 1.2, "excellent": 1.3, "awesome": 1.3, "amazing": 1.3,
    "love": 1.3, "like": 0.8, "thanks": 0.9, "thank": 0.9, "perfect": 1.2,
    "helpful": 1.0, "nice": 0.9, "cool": 0.8, "brilliant": 1.2, "fantastic": 1.3,
    "happy": 1.1, "glad": 0.9, "appreciate": 1.0, "wonderful": 1.3, "yes": 0.5,
    "work": 0.4, "works": 0.6, "solved": 0.9, "fixed": 0.7, "correct": 0.6,
    "beautiful": 1.0, "fast": 0.8, "smooth": 0.8, "clean": 0.6, "好": 1.0, "好的": 1.0,
}
_NEG = {
    "bad": -1.0, "terrible": -1.4, "awful": -1.3, "hate": -1.3, "broken": -1.1,
    "bug": -0.7, "error": -0.6, "fail": -1.0, "failed": -1.1, "failing": -1.0,
    "wrong": -1.0, "useless": -1.3, "slow": -0.7, "crash": -1.2, "crashé": -1.2,
    "confusing": -0.8, "annoying": -1.1, "angry": -1.2, "frustrating": -1.2,
    "frustrated": -1.2, "annoyed": -1.0, "stupid": -1.3, "worse": -1.0, "awful": -1.3,
    "problem": -0.7, "issue": -0.5, "stuck": -0.8, "help": 0.2, "please": 0.1,
    "sorry": -0.4, "urgent": -0.3, "糟糕": -1.2, "错误": -1.0, "失败": -1.0,
}
_NEGATORS = {"not", "no", "never", "cannot", "can't", "won't", "don't", "doesn't",
             "isn't", "aren't", "wasn't", "without", "hardly", "barely", "n't"}
_INTENS = {"very": 1.5, "really": 1.4, "so": 1.3, "extremely": 1.8, "super": 1.5,
           "totally": 1.4, "absolutely": 1.6, "incredibly": 1.7, "太": 1.5, "非常": 1.6}
_EMO = {
    "anger": {"angry", "furious", "mad", "rage", "annoyed", "hate", "unacceptable",
              "ridiculous", "wtf", "气得", "生气"},
    "frustration": {"frustrated", "frustrating", "stuck", "still", "again", "why",
                    "doesn't work", "not working", "useless", "麻烦", "还是"},
    "joy": {"love", "great", "awesome", "amazing", "happy", "thanks", "perfect",
            "excellent", "太好了", "开心"},
    "curiosity": {"how", "why", "what", "curious", "wonder", "explain", "learn",
                  "如何", "为什么"},
    "fear": {"worried", "scared", "afraid", "danger", "risk", "vulnerab", "threat",
             "security", "担心", "害怕"},
    "sadness": {"sad", "unhappy", "disappointed", "sorry", "depressed", "难过"},
    "surprise": {"wow", "surprised", "unexpected", "whoa", "amazed", "居然"},
}
_FENCE = re.compile(r"```")
_URL = re.compile(r"https?://[^\s<>\"')]+")
_FILE = re.compile(r"\b[\w./-]+\.(?:py|js|ts|tsx|jsx|java|kt|go|rs|c|cpp|h|rb|php|md|json|ya?ml|html|css|sh|sql|toml|ini)\b")
_PKG = re.compile(r"\b(?:pip|npm|pnpm|yarn|cargo|go get|apt|brew)\s+(?:install\s+)?([\w@/.-]+)")
_VER = re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b")
_DIFF = re.compile(
    r"architect|design system|root cause|race condition|deadlock|security|vulnerab|"
    r"migrat|refactor|monorepo|distributed|consensus|split-brain|threat model", re.I)
_CODE = re.compile(r"```|def |function |class |import |SELECT |fn\(|=>|\{\s*\"", re.I)
_URGENT = {"asap", "immediately", "urgent", "right now", "deadline", "quickly",
           "hurry", "立刻", "马上", "急"}
_INTENT = [
    ("generate_video", r"\b(video|animate|animation|clip|movie|motion)\b"),
    ("generate_image", r"\b(image|picture|photo|draw|render|logo|illustration|art)\b.*\b(generate|make|create|draw|render)\b|\b(generate|make|create|draw)\b.*\b(image|picture|logo)\b"),
    ("translate", r"\b(translate|translation|in (?:french|spanish|german|hindi|bengali|chinese|arabic|japanese))\b"),
    ("summarize", r"\b(summar|tl;?dr|condense|shorten|boil down)\b"),
    ("audit", r"\b(audit|security review|pentest|vulnerab|threat|malware|scan)\b"),
    ("debug", r"\b(debug|error|traceback|exception|stack ?trace|bug|fails?|crash|not working|broken)\b"),
    ("refactor", r"\b(refactor|clean ?up|restructure|rewrite|optimi[sz]e)\b"),
    ("build", r"\b(build|create|implement|add|write|make|develop|scaffold|generate)\b"),
    ("explain", r"\b(explain|what is|what are|how does|why does|meaning of|difference between)\b"),
    ("ask", r"\?$|\b(can you|could you|would you|help me|tell me|show me)\b"),
]
_REDFLAG = {
    "self-harm": r"\b(kill myself|suicide|suicidal|end my life|self[- ]?harm|hurt myself)\b",
    "weapon": r"\b(build|make|synthesize)\b.{0,40}\b(bomb|explosive|nerve agent|bioweapon|grenade)\b",
    "csam": r"\b(child|minor|underage)\b.{0,25}\b(porn|sexual|nude)\b",
}


def _words(text):
    return re.findall(r"[a-zA-ZÀ-ÿ']+|[\u4E00-\u9FFF]+", (text or "").lower())


def sentiment(text: str) -> dict:
    ws = _words(text)
    if not ws:
        return {"label": "neutral", "score": 0.0, "confidence": 0.0}
    total, pos_hits, neg_hits = 0.0, 0, 0
    for i, w in enumerate(ws):
        val = _POS.get(w, 0.0) + _NEG.get(w, 0.0)
        if not val:
            continue
        mult = 1.0
        for j in range(max(0, i - 2), i):
            if ws[j] in _INTENS:
                mult *= _INTENS[ws[j]]
            if ws[j] in _NEGATORS:
                mult *= -1.0
        total += val * mult
        if val > 0:
            pos_hits += 1
        else:
            neg_hits += 1
    denom = max(len(ws) ** 0.5, 1.0)
    score = max(-1.0, min(1.0, total / denom))
    hits = pos_hits + neg_hits
    label = "positive" if score > 0.12 else "negative" if score < -0.12 else "neutral"
    conf = min(1.0, hits / 4.0) * min(1.0, abs(score) * 2 + 0.3)
    return {"label": label, "score": round(score, 3), "confidence": round(conf, 3)}


def intensity(text: str) -> float:
    t = text or ""
    if not t.strip():
        return 0.0
    words = _words(t)
    caps = sum(1 for c in t if c.isupper())
    letters = sum(1 for c in t if c.isalpha()) or 1
    caps_ratio = caps / letters
    bangs = t.count("!") + t.count("？") + t.count("?") * 0.3
    intens = sum(1 for w in words if w in _INTENS)
    return round(min(1.0, 0.15 + 0.5 * caps_ratio + 0.12 * min(bangs, 5) +
                     0.1 * min(intens, 3)), 3)


def emotion(text: str, sent: dict) -> str:
    low = (text or "").lower()
    best, best_hits = "neutral", 0
    for name, kws in _EMO.items():
        hits = sum(1 for k in kws if k in low)
        if hits > best_hits:
            best, best_hits = name, hits
    if best != "neutral":
        return best
    if sent["label"] == "positive":
        return "joy"
    if sent["label"] == "negative":
        return "frustration"
    return "neutral"


def urgency(text: str) -> float:
    low = (text or "").lower()
    hits = sum(1 for k in _URGENT if k in low)
    return round(min(1.0, hits * 0.4), 3)


def intent(text: str) -> str:
    t = text or ""
    for name, pat in _INTENT:
        if re.search(pat, t, re.I):
            return name
    if len(t.split()) <= 4 and not _CODE.search(t):
        return "chitchat"
    return "ask"


def entities(text: str) -> list:
    t = text or ""
    out, seen = [], set()

    def add(kind, val):
        key = (kind, val)
        if key not in seen:
            seen.add(key)
            out.append({"type": kind, "value": val})

    for u in _URL.findall(t)[:6]:
        add("url", u)
    for f in _FILE.findall(t)[:8]:
        add("file", f)
    for p in _PKG.findall(t)[:5]:
        add("pkg", p)
    fence_langs = re.findall(r"```(\w+)", t)
    for l in fence_langs[:4]:
        if l:
            add("lang", l)
    for v in _VER.findall(t)[:5]:
        add("version", v)
    return out


def topics(text: str, k: int = 6) -> list:
    ws = [w for w in _words(text) if len(w) > 3 and w not in _STOP["en"]]
    freq = {}
    for w in ws:
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def complexity(text: str, ents: list) -> float:
    t = text or ""
    words = len(t.split())
    score = 0.0
    score += min(1.0, words / 300.0) * 0.45
    if _CODE.search(t):
        score += 0.15
    if _FENCE.search(t) and t.count("```") >= 4:
        score += 0.1
    if _DIFF.search(t):
        score += 0.2
    files = sum(1 for e in ents if e["type"] == "file")
    if files >= 3:
        score += 0.15
    if t.count("?") >= 3:
        score += 0.1
    return round(min(1.0, score), 3)


def redflags(text: str) -> list:
    low = (text or "").lower()
    return [name for name, pat in _REDFLAG.items() if re.search(pat, low, re.I)]


def analyze(text: str, history=None) -> dict:
    """Full request understanding. Deterministic, network-free, never raises."""
    try:
        t = text or ""
        sent = sentiment(t)
        ents = entities(t)
        return {
            "language": detect_language(t),
            "sentiment": sent,
            "emotion": emotion(t, sent),
            "intensity": intensity(t),
            "urgency": urgency(t),
            "intent": intent(t),
            "entities": ents,
            "topics": topics(t),
            "complexity": complexity(t, ents),
            "redflags": redflags(t),
            "chars": len(t),
            "words": len(t.split()),
        }
    except Exception:
        return {"language": "en", "sentiment": {"label": "neutral", "score": 0.0,
                "confidence": 0.0}, "emotion": "neutral", "intensity": 0.0,
                "urgency": 0.0, "intent": "ask", "entities": [], "topics": [],
                "complexity": 0.0, "redflags": [], "chars": 0, "words": 0}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(analyze(" ".join(sys.argv[1:]) or "hello"), indent=2))
