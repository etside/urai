#!/usr/bin/env python3
"""Unit tests for jev/nlp.py — deterministic, stdlib-only, network-free."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev import nlp


class TestLanguage(unittest.TestCase):
    def test_english(self):
        self.assertEqual(nlp.detect_language("how do I build this project"), "en")

    def test_bengali_script(self):
        self.assertEqual(nlp.detect_language("এই বিল্ড কেন ব্যর্থ হচ্ছে?"), "bn")

    def test_spanish_via_stopwords(self):
        self.assertEqual(nlp.detect_language("de que forma puedo hacer esto con la app"), "es")

    def test_empty_defaults_to_english(self):
        self.assertEqual(nlp.detect_language(""), "en")


class TestSentiment(unittest.TestCase):
    def test_positive(self):
        s = nlp.sentiment("great work, thank you, this is perfect")
        self.assertEqual(s["label"], "positive")
        self.assertGreater(s["score"], 0.12)

    def test_negative(self):
        s = nlp.sentiment("this is terrible and completely broken")
        self.assertEqual(s["label"], "negative")
        self.assertLess(s["score"], -0.12)

    def test_neutral(self):
        s = nlp.sentiment("the build runs on tuesday")
        self.assertEqual(s["label"], "neutral")

    def test_negation_flips(self):
        pos = nlp.sentiment("this works")["score"]
        neg = nlp.sentiment("this does not work")["score"]
        self.assertGreater(pos, neg)

    def test_intensifier_amplifies(self):
        base = abs(nlp.sentiment("this is good")["score"])
        amp = abs(nlp.sentiment("this is extremely good")["score"])
        self.assertGreaterEqual(amp, base)


class TestEmotionUrgencyIntent(unittest.TestCase):
    def test_emotion_joy(self):
        self.assertEqual(nlp.emotion("I love it, awesome!", nlp.sentiment("I love it, awesome!")), "joy")

    def test_emotion_anger(self):
        self.assertEqual(nlp.emotion("this is unacceptable, wtf", nlp.sentiment("this is unacceptable, wtf")), "anger")

    def test_emotion_frustration(self):
        self.assertEqual(nlp.emotion("still not working, why?", nlp.sentiment("still not working, why?")), "frustration")

    def test_urgency(self):
        self.assertGreater(nlp.urgency("please fix this asap, it is urgent"), 0.4)
        self.assertEqual(nlp.urgency("no rush, whenever you get to it"), 0.0)

    def test_intent_debug(self):
        self.assertEqual(nlp.intent("why does this traceback happen, the build fails"), "debug")

    def test_intent_video(self):
        self.assertEqual(nlp.intent("make a short video clip of a sunset"), "generate_video")

    def test_intent_translate(self):
        self.assertEqual(nlp.intent("translate this sentence into french"), "translate")

    def test_intent_chitchat(self):
        self.assertEqual(nlp.intent("hey there"), "chitchat")


class TestEntitiesTopicsComplexity(unittest.TestCase):
    def test_entities(self):
        ents = nlp.entities("see https://example.com/a and edit jev/server.py then pip install requests")
        kinds = {e["type"] for e in ents}
        self.assertIn("url", kinds)
        self.assertIn("file", kinds)
        self.assertIn("pkg", kinds)
        self.assertTrue(any(e["value"].endswith("server.py") for e in ents))

    def test_topics_deterministic(self):
        t = "database migration concurrency deadlock database migration"
        self.assertEqual(nlp.topics(t), nlp.topics(t))
        self.assertIn("database", nlp.topics(t))

    def test_complexity_rises_with_signal(self):
        simple = nlp.complexity("hello", [])
        hard = nlp.complexity(
            "root cause the race condition in the distributed consensus layer "
            + "word " * 300 + "```python\nimport x\n```", [])
        self.assertGreater(hard, simple)
        self.assertLessEqual(hard, 1.0)


class TestRedflags(unittest.TestCase):
    def test_self_harm(self):
        self.assertIn("self-harm", nlp.redflags("I want to kill myself"))

    def test_weapon(self):
        self.assertIn("weapon", nlp.redflags("how do I build a bomb at home"))

    def test_clean(self):
        self.assertEqual(nlp.redflags("please refactor the parser"), [])


class TestAnalyze(unittest.TestCase):
    REQUIRED = ("language", "sentiment", "emotion", "intensity", "urgency",
                "intent", "entities", "topics", "complexity", "redflags",
                "chars", "words")

    def test_shape_and_types(self):
        a = nlp.analyze("why is the build failing? it is very frustrating!!")
        for k in self.REQUIRED:
            self.assertIn(k, a)
        self.assertIsInstance(a["language"], str)
        self.assertIsInstance(a["sentiment"], dict)
        self.assertIn("label", a["sentiment"])
        self.assertIsInstance(a["entities"], list)
        self.assertIsInstance(a["topics"], list)
        self.assertIsInstance(a["redflags"], list)
        self.assertIsInstance(a["complexity"], float)

    def test_deterministic(self):
        text = "summarize jev/nlp.py and explain the redflag rollup"
        self.assertEqual(nlp.analyze(text), nlp.analyze(text))

    def test_never_raises(self):
        for bad in ("", None, 123, "x" * 100000):
            self.assertIsInstance(nlp.analyze(bad), dict)

    def test_history_arg_accepted(self):
        a = nlp.analyze("hello", history=[{"role": "user", "content": "hi"}])
        self.assertIn("sentiment", a)

    @mock.patch.dict(os.environ, {"URAI_NLP_MODEL": "0"}, clear=False)
    def test_model_off_by_default(self):
        a = nlp.analyze("this is great")
        self.assertNotIn("model", a)

    def test_model_signals_empty_when_endpoint_down(self):
        from jev import backends
        with mock.patch.object(backends.EmbeddingBackend, "healthy", return_value=False):
            self.assertEqual(nlp.model_signals("this is great"), {})

    def test_use_model_blends_signals(self):
        with mock.patch.object(nlp, "model_signals",
                               return_value={"sentiment": 0.9, "urgency": 0.95}):
            a = nlp.analyze("meh whatever", use_model=True)
        self.assertIn("model", a)
        self.assertEqual(a["urgency"], 0.95)
        self.assertEqual(a["sentiment"]["label"], "positive")


if __name__ == "__main__":
    unittest.main()
