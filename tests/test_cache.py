#!/usr/bin/env python3
"""Unit tests for jev/cache.py — hit, miss, near-identical, TTL, invalidation."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev.cache import PromptCache, similarity


def msg(text):
    return [{"role": "user", "content": text}]


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class TestBasicHitMiss(unittest.TestCase):
    def setUp(self):
        self.c = PromptCache(max_entries=16, ttl_seconds=100, similarity=0.0,
                             enabled=True, clock=FakeClock())

    def test_miss_then_stats(self):
        self.assertIsNone(self.c.get("urai", msg("hello"), 64, 0.2))
        s = self.c.stats()
        self.assertEqual(s["misses"], 1)
        self.assertEqual(s["hits"], 0)

    def test_exact_hit(self):
        self.c.put("urai", msg("hello there"), 64, 0.2, "hi!")
        self.assertEqual(self.c.get("urai", msg("hello there"), 64, 0.2), "hi!")
        s = self.c.stats()
        self.assertEqual(s["hits"], 1)
        self.assertEqual(s["exact_hits"], 1)
        self.assertEqual(s["hit_rate"], 1.0)

    def test_key_includes_params(self):
        self.c.put("urai", msg("hello"), 64, 0.2, "A")
        self.assertIsNone(self.c.get("urai", msg("hello"), 128, 0.2))
        self.assertIsNone(self.c.get("urai", msg("hello"), 64, 0.7))
        self.assertIsNone(self.c.get("cyberurai", msg("hello"), 64, 0.2))


class TestSimilarity(unittest.TestCase):
    def test_similarity_function(self):
        self.assertEqual(similarity("reset my password", "reset my password"), 1.0)
        self.assertAlmostEqual(similarity("reset my password", "reset the password"), 0.5)
        self.assertEqual(similarity("a b", "c d"), 0.0)
        self.assertEqual(similarity("", "abc"), 0.0)

    def test_near_identical_hit(self):
        c = PromptCache(similarity=0.9, ttl_seconds=100, enabled=True,
                        clock=FakeClock())
        c.put("urai", msg("how do I reset my password"), 64, 0.2, "use Settings")
        # punctuation/case only differ -> token sets identical
        got = c.get("urai", msg("How do I reset my password?"), 64, 0.2)
        self.assertEqual(got, "use Settings")
        self.assertEqual(c.stats()["similar_hits"], 1)

    def test_below_threshold_misses(self):
        c = PromptCache(similarity=0.9, ttl_seconds=100, enabled=True,
                        clock=FakeClock())
        c.put("urai", msg("reset my password"), 64, 0.2, "x")
        self.assertIsNone(c.get("urai", msg("reset the password now please"), 64, 0.2))

    def test_similarity_disabled_is_exact_only(self):
        c = PromptCache(similarity=0.0, ttl_seconds=100, enabled=True,
                        clock=FakeClock())
        c.put("urai", msg("reset my password"), 64, 0.2, "x")
        self.assertIsNone(c.get("urai", msg("Reset my password!"), 64, 0.2))

    def test_similarity_not_cross_params(self):
        c = PromptCache(similarity=0.9, ttl_seconds=100, enabled=True,
                        clock=FakeClock())
        c.put("urai", msg("hello world"), 64, 0.2, "x")
        self.assertIsNone(c.get("urai", msg("hello world"), 128, 0.2))


class TestTTL(unittest.TestCase):
    def test_ttl_expiry(self):
        clock = FakeClock()
        c = PromptCache(ttl_seconds=60, similarity=0.0, enabled=True, clock=clock)
        c.put("urai", msg("hello"), 64, 0.2, "hi")
        self.assertEqual(c.get("urai", msg("hello"), 64, 0.2), "hi")
        clock.advance(61)
        self.assertIsNone(c.get("urai", msg("hello"), 64, 0.2))
        self.assertGreaterEqual(c.stats()["expires"], 1)
        self.assertEqual(c.stats()["size"], 0)

    def test_expire_sweep(self):
        clock = FakeClock()
        c = PromptCache(ttl_seconds=10, similarity=0.0, enabled=True, clock=clock)
        c.put("urai", msg("a"), 64, 0.2, "1")
        c.put("urai", msg("b"), 64, 0.2, "2")
        clock.advance(11)
        self.assertEqual(c.expire(), 2)
        self.assertEqual(c.stats()["size"], 0)


class TestInvalidation(unittest.TestCase):
    def test_clear(self):
        c = PromptCache(similarity=0.0, enabled=True, clock=FakeClock())
        c.put("urai", msg("a"), 64, 0.2, "1")
        c.put("urai", msg("b"), 64, 0.2, "2")
        self.assertEqual(c.clear()["cleared"], 2)
        self.assertIsNone(c.get("urai", msg("a"), 64, 0.2))
        self.assertEqual(c.stats()["size"], 0)
        self.assertEqual(c.stats()["clears"], 1)

    def test_invalidate_predicate(self):
        c = PromptCache(similarity=0.0, enabled=True, clock=FakeClock())
        c.put("urai", msg("a"), 64, 0.2, "1")
        c.put("cyberurai", msg("a"), 64, 0.2, "2")
        removed = c.invalidate(lambda e: e["model"] == "urai")
        self.assertEqual(removed, 1)
        self.assertIsNone(c.get("urai", msg("a"), 64, 0.2))
        self.assertEqual(c.get("cyberurai", msg("a"), 64, 0.2), "2")


class TestEvictionAndDisable(unittest.TestCase):
    def test_lru_eviction(self):
        c = PromptCache(max_entries=2, similarity=0.0, enabled=True, clock=FakeClock())
        c.put("urai", msg("a"), 64, 0.2, "1")
        c.put("urai", msg("b"), 64, 0.2, "2")
        c.put("urai", msg("c"), 64, 0.2, "3")
        self.assertEqual(c.stats()["size"], 2)
        self.assertGreaterEqual(c.stats()["evictions"], 1)

    def test_disabled_bypasses(self):
        c = PromptCache(enabled=False, similarity=0.9, clock=FakeClock())
        c.put("urai", msg("a"), 64, 0.2, "1")
        self.assertIsNone(c.get("urai", msg("a"), 64, 0.2))
        s = c.stats()
        self.assertFalse(s["enabled"])
        self.assertEqual(s["bypassed"], 1)
        self.assertEqual(s["size"], 0)

    def test_stats_shape(self):
        s = PromptCache(clock=FakeClock()).stats()
        for k in ("enabled", "hits", "exact_hits", "similar_hits", "misses",
                  "bypassed", "hit_rate", "size", "max", "ttl_s", "similarity",
                  "evictions", "expires", "clears"):
            self.assertIn(k, s)


if __name__ == "__main__":
    unittest.main()
