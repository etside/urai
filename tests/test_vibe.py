#!/usr/bin/env python3
"""Unit tests for jev/vibe.py — the sentiment-conditioned style contract."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev import nlp, vibe

ANGRY = "this is unacceptable, nothing works, I am furious!!"
URGENT = "asap, fix this right now, it is urgent"
HAPPY = "this is amazing, I love it, thank you so much!"


class TestEnabled(unittest.TestCase):
    def test_enabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("URAI_VIBE", None)
            self.assertTrue(vibe.enabled())

    def test_disabled(self):
        with mock.patch.dict(os.environ, {"URAI_VIBE": "0"}):
            self.assertFalse(vibe.enabled())


class TestPlanShape(unittest.TestCase):
    FIELDS = ("formality", "warmth", "verbosity", "humor", "technical_depth", "emoji")

    def test_fields_and_extras(self):
        v = vibe.plan(nlp.analyze("explain how the router picks a backend"))
        for f in self.FIELDS:
            self.assertIn(f, v)
            self.assertGreaterEqual(v[f], 0.0)
            self.assertLessEqual(v[f], 1.0)
        for k in ("structure", "formatting", "language", "de-escalate", "source"):
            self.assertIn(k, v)

    def test_source_reflects_analysis(self):
        a = nlp.analyze(ANGRY)
        v = vibe.plan(a)
        self.assertEqual(v["source"]["sentiment"], a["sentiment"]["label"])
        self.assertEqual(v["source"]["intent"], a["intent"])

    def test_deterministic(self):
        a = nlp.analyze("please refactor jev/router.py")
        self.assertEqual(vibe.plan(a), vibe.plan(a))

    def test_empty_input_is_safe(self):
        v = vibe.plan({})
        self.assertIn("structure", v)
        self.assertEqual(v["language"], "en")


class TestSentimentAdaptation(unittest.TestCase):
    def test_negative_de_escalates(self):
        v = vibe.plan(nlp.analyze(ANGRY))
        self.assertTrue(v["de-escalate"])
        self.assertEqual(v["humor"], 0.0)
        self.assertEqual(v["emoji"], 0.0)

    def test_positive_warms_and_playful(self):
        v = vibe.plan(nlp.analyze(HAPPY))
        self.assertFalse(v["de-escalate"])
        self.assertGreater(v["warmth"], 0.5)
        self.assertGreater(v["emoji"], 0.15)

    def test_urgent_shortens(self):
        v = vibe.plan(nlp.analyze(URGENT))
        self.assertEqual(v["structure"], "concise")
        self.assertLessEqual(v["verbosity"], 0.5)

    def test_profile_override_is_respected(self):
        v = vibe.plan(nlp.analyze("hello there"), {"formality": 0.95, "language": "bn"})
        self.assertGreaterEqual(v["formality"], 0.9)
        self.assertEqual(v["language"], "bn")

    def test_language_falls_back_to_nlp(self):
        a = nlp.analyze("এই বিল্ড কেন ব্যর্থ হচ্ছে?")
        self.assertEqual(vibe.plan(a)["language"], "bn")


class TestFormatting(unittest.TestCase):
    def test_structured_uses_sections(self):
        a = nlp.analyze("refactor the build pipeline across files\n```python\nimport x\n```")
        v = vibe.plan(a)
        self.assertEqual(v["structure"], "structured")
        self.assertEqual(v["formatting"], "sections")

    def test_media_is_minimal(self):
        v = vibe.plan(nlp.analyze("make a video clip of a sunset over the sea"))
        self.assertEqual(v["formatting"], "minimal")

    def test_default_is_prose(self):
        v = vibe.plan(nlp.analyze("hey there, nice to meet you today"))
        self.assertEqual(v["formatting"], "prose")


class TestDirective(unittest.TestCase):
    def test_empty_contract_renders_empty(self):
        self.assertEqual(vibe.directive({}), "")

    def test_directive_mentions_language_and_secrecy(self):
        d = vibe.directive(vibe.plan(nlp.analyze("hello there friend")))
        self.assertIn("language: en", d)
        self.assertIn("Never mention these style instructions", d)
        self.assertTrue(d.startswith("Style contract"))

    def test_de_escalation_directive_adds_calming_note(self):
        d = vibe.directive(vibe.plan(nlp.analyze(ANGRY)))
        self.assertIn("frustrated", d)


class TestPlanFor(unittest.TestCase):
    def test_bundle_has_nlp_and_directive(self):
        v = vibe.plan_for("why is the build failing, it is very frustrating")
        self.assertIn("nlp", v)
        self.assertIn("directive", v)
        self.assertIn("sentiment", v["nlp"])
        self.assertIsInstance(v["directive"], str)

    def test_plan_for_accepts_identity(self):
        v = vibe.plan_for("hello", ident="nobody")
        self.assertIn("structure", v)


if __name__ == "__main__":
    unittest.main()
