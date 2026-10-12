#!/usr/bin/env python3
"""Teacher client interface for ownai distillation (Phase 2 prototype).

Providers implement `generate(task) -> TeacherOutput`. No API keys are
needed to build/test: MockTeacher runs fully offline. Real teachers attach
later via OpenAICompatibleTeacher (OpenRouter, Gemini-OAI endpoint, or a
local llama-server) using env vars only — keys never live in this repo.

    export TEACHER_BASE_URL=https://openrouter.ai/api/v1
    export TEACHER_API_KEY=...
    export TEACHER_MODEL=<model id>
"""

import json
import os
import urllib.request
from dataclasses import dataclass


@dataclass
class TeacherOutput:
    content: str
    model: str
    meta: dict


class Teacher:
    name = "base"

    def generate(self, task: dict) -> TeacherOutput:
        raise NotImplementedError


class MockTeacher(Teacher):
    """Deterministic offline stand-in. Returns KNOWN-GOOD or KNOWN-BAD
    outputs so the verifier/filter stages can be tested without any key."""

    name = "mock-v1"

    def generate(self, task: dict) -> TeacherOutput:
        tid = task.get("id", "")
        if tid.endswith("bad"):
            content = (
                "Here is the fix:\n```python\nimport os\n"
                "password = 'hunter2'\nresult = eval(user_input)\n```\n"
                '{"status": ok, broken json,,,}'
            )
        else:
            content = task.get("reference_good", "No reference provided.")
        return TeacherOutput(content=content, model=self.name, meta={})


class OpenAICompatibleTeacher(Teacher):
    """Any OpenAI-chat-completions-compatible endpoint (OpenRouter,
    Gemini OpenAI endpoint, local llama-server, vLLM, ...)."""

    name = "oai-compatible"

    def __init__(self):
        self.base = os.environ["TEACHER_BASE_URL"].rstrip("/")
        self.key = os.environ["TEACHER_API_KEY"]
        self.model = os.environ.get("TEACHER_MODEL", "")
        if not self.model:
            raise RuntimeError("TEACHER_MODEL env var is required")

    def generate(self, task: dict) -> TeacherOutput:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": task.get("system", DEFAULT_SYSTEM)},
                {"role": "user", "content": task["prompt"]},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            self.base + "/chat/completions",
            json.dumps(payload).encode(),
            {"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
        return TeacherOutput(
            content=data["choices"][0]["message"]["content"],
            model=self.model,
            meta={"id": data.get("id", "")},
        )


class FreeCliTeacher(Teacher):
    """Free-tier teacher via the local opencode CLI (no API key needed).

    Uses models the CLI may spend from the free tier, e.g.
    opencode/muse-spark-1.3-contributor-free (default). Enable with:
        export URAI_FREE_TEACHER=1
        export URAI_FREE_MODEL="opencode/muse-spark-1.3-contributor-free"
    Optional: URAI_FREE_TIMEOUT (seconds per call, default 180),
    OPENCODE_BIN (default: opencode on PATH, else ~/.opencode/bin/opencode).

    Slow by design (one subprocess per task, ~10-30s) — run it in the
    background and let it grind through hundreds of tasks for free.
    """

    name = "free-cli"

    def __init__(self):
        import shutil
        self.model = os.environ.get(
            "URAI_FREE_MODEL", "opencode/muse-spark-1.3-contributor-free")
        self.timeout = int(os.environ.get("URAI_FREE_TIMEOUT", "180"))
        self.bin = os.environ.get("OPENCODE_BIN") or shutil.which("opencode") \
            or os.path.expanduser("~/.opencode/bin/opencode")

    def generate(self, task: dict) -> TeacherOutput:
        import subprocess
        system = task.get("system", DEFAULT_SYSTEM)
        prompt = system + "\n\nTASK:\n" + task["prompt"]
        try:
            p = subprocess.run(
                [self.bin, "run", "--model", self.model, prompt],
                capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"free teacher timed out after {self.timeout}s")
        if p.returncode != 0:
            raise RuntimeError(f"free teacher exit {p.returncode}: "
                               f"{(p.stderr or p.stdout)[-300:]}")
        text = p.stdout
        # strip CLI header lines like "> build · <model>"
        lines = [ln for ln in text.splitlines()
                 if not ln.strip().startswith(">")]
        content = "\n".join(lines).strip()
        if not content:
            raise RuntimeError("free teacher returned empty answer")
        return TeacherOutput(content=content, model=self.model, meta={})


class PuterBackend(Teacher):
    """Puter.com AI (free account, user-pays allowance, no credit card).

    Sign up free at https://puter.com, create a token, then:
        export PUTER_API_KEY="<puter user token>"
        export PUTER_MODEL="qwen3-max"   # any model id your account can use
    Optional override: PUTER_BASE_URL (default https://api.puter.com/v2/ai/chat).
    Response shapes vary by upstream model, so content is extracted
    defensively (OpenAI-style first, Puter-native fallbacks).
    """

    name = "puter"

    def __init__(self):
        self.base = os.environ.get("PUTER_BASE_URL",
                                   "https://api.puter.com/v2/ai/chat").rstrip("/")
        self.key = os.environ["PUTER_API_KEY"]
        self.model = os.environ.get("PUTER_MODEL", "")

    @staticmethod
    def _content(data) -> str:
        try:
            return data["choices"][0]["message"]["content"]
        except Exception:
            pass
        for path in (["message", "content"], ["result", "content"],
                     ["text"], ["content"], ["output"]):
            cur = data
            try:
                for k in path:
                    cur = cur[k]
                if isinstance(cur, str) and cur.strip():
                    return cur
            except Exception:
                continue
        raise KeyError(f"unrecognized Puter response keys: {list(data)[:8]}")

    def generate(self, task: dict) -> TeacherOutput:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": task.get("system", DEFAULT_SYSTEM)},
                {"role": "user", "content": task["prompt"]},
            ],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            self.base, json.dumps(payload).encode(),
            {"Content-Type": "application/json",
             "Authorization": "Bearer " + self.key},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
        content = self._content(data)
        meta = {"id": data.get("id", "")} if isinstance(data, dict) else {}
        return TeacherOutput(content=content, model=self.model or "puter",
                             meta=meta)


DEFAULT_SYSTEM = (
    "You are a senior software engineer. Output production-quality code with "
    "tests, edge cases and error handling. Never invent APIs, files, or "
    "benchmark results. If unsure, say so."
)

# Reasoning-distill mode (DeepSeek-R1 style): the teacher thinks first in a
# ```think block, then gives the final answer. The trace is kept as training
# signal (small models learn the reasoning, not just the answer).
# Use: run_distill.py --system reasoning (with a reasoning teacher such as
# DeepSeek-R1-Distill, Qwen3-thinking, or any strong chat model).
REASONING_SYSTEM = (
    "You are a senior software engineer who reasons step by step. First "
    "write your analysis in a ```think block (plan, edge cases, why other "
    "approaches fail). Then output the final production-quality answer with "
    "tests and error handling. Never invent APIs, files, or benchmark "
    "results. If unsure, say so inside the think block and keep the answer "
    "minimal."
)

SYSTEMS = {"default": DEFAULT_SYSTEM, "reasoning": REASONING_SYSTEM}


def get_teacher() -> Teacher:
    if os.environ.get("TEACHER_API_KEY") and os.environ.get("TEACHER_BASE_URL"):
        return OpenAICompatibleTeacher()
    if os.environ.get("PUTER_API_KEY"):
        return PuterBackend()
    if os.environ.get("URAI_FREE_TEACHER") == "1":
        return FreeCliTeacher()
    return MockTeacher()
