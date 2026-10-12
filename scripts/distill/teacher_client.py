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


DEFAULT_SYSTEM = (
    "You are a senior software engineer. Output production-quality code with "
    "tests, edge cases and error handling. Never invent APIs, files, or "
    "benchmark results. If unsure, say so."
)


def get_teacher() -> Teacher:
    if os.environ.get("TEACHER_API_KEY") and os.environ.get("TEACHER_BASE_URL"):
        return OpenAICompatibleTeacher()
    return MockTeacher()
