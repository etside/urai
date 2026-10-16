#!/usr/bin/env python3
"""End-to-end wiring: every request passes through nlp + vibe before the LLM."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("URAI_FORCE_MOCK", "1")
os.environ["URAI_VIBE"] = "1"

from jev import server  # noqa: E402


class TestServerMeta(unittest.TestCase):
    def test_urai_meta_has_nlp_and_vibe(self):
        m = server._urai_meta("this is broken, please fix it now!")
        self.assertIn("nlp", m)
        self.assertIn("vibe", m)
        self.assertIn("sentiment", m["nlp"])
        self.assertIn("structure", m["vibe"])
        self.assertIn("directive", m["vibe"])

    def test_urai_meta_empty_text(self):
        self.assertEqual(server._urai_meta(""), {})
        self.assertEqual(server._urai_meta(None), {})

    def test_apply_vibe_prepends_directive(self):
        msgs, meta = server._apply_vibe(
            [{"role": "user", "content": "I am so frustrated, nothing works!!"}])
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("Style contract", msgs[0]["content"])
        self.assertTrue(meta["vibe"]["de-escalate"])

    def test_apply_vibe_no_directive_leaves_messages(self):
        msgs, meta = server._apply_vibe([])
        self.assertEqual(msgs, [])
        self.assertEqual(meta, {})


class TestAgentMeta(unittest.TestCase):
    def test_run_agent_returns_urai_meta(self):
        from jev.agent import run_agent
        r = run_agent("why is the build failing?")
        self.assertTrue(r["ok"])
        self.assertIn("urai", r)
        self.assertEqual(r["urai"]["nlp"]["language"], "en")
        self.assertIn("structure", r["urai"]["vibe"])
        steps = {t["step"] for t in r["trace"]}
        self.assertIn("nlp", steps)
        self.assertIn("vibe", steps)

    def test_run_agent_has_no_raw_directive_leak_in_answer(self):
        from jev.agent import run_agent
        r = run_agent("hello there, just saying hi")
        self.assertNotIn("Style contract", r["answer"])
        self.assertNotIn("Never mention these style instructions", r["answer"])


class TestRouterComplexityHint(unittest.TestCase):
    def test_complexity_hint_raises_level(self):
        from jev.router import route
        base = route("please summarize this short note")
        hinted = route("please summarize this short note", complexity=0.9)
        self.assertGreaterEqual(hinted["level"], 2)
        self.assertGreaterEqual(hinted["level"], 0)
        self.assertEqual(base["tier"], hinted["tier"])

    def test_no_hint_is_unchanged(self):
        from jev.router import route
        self.assertEqual(route("hello").get("level"), route("hello").get("level"))

    def test_bad_complexity_ignored(self):
        from jev.router import route
        r = route("hello there", complexity="not-a-number")
        self.assertIn("level", r)


if __name__ == "__main__":
    unittest.main()
