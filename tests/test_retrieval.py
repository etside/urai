#!/usr/bin/env python3
"""Unit tests for jev/retrieval.py — indexing, top-K, recency weighting."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jev import retrieval

NOW = 1_700_000_000.0
DAY = 86400.0


def chunk(text, kind="fact", source="memory", ts=NOW, cid="1"):
    return {"text": text, "kind": kind, "id": cid, "ts": ts, "source": source}


class TestIndexing(unittest.TestCase):
    def test_chunks_merge_memory_and_focus(self):
        mem = [chunk("deployed urai v2", source="memory", cid="m1")]
        foc = [chunk("finishing phase 2", kind="focus", source="focus", cid="f1")]
        with mock.patch.object(retrieval, "_memory_chunks", return_value=mem), \
             mock.patch.object(retrieval, "_focus_chunks", return_value=foc):
            ch = retrieval.chunks()
        self.assertEqual(len(ch), 2)
        self.assertEqual({c["source"] for c in ch}, {"memory", "focus"})

    def test_chunks_sources_filter(self):
        with mock.patch.object(retrieval, "_memory_chunks", return_value=[chunk("m")]), \
             mock.patch.object(retrieval, "_focus_chunks", return_value=[chunk("f", kind="focus", source="focus")]):
            self.assertEqual(len(retrieval.chunks(("memory",))), 1)
            self.assertEqual(len(retrieval.chunks(("focus",))), 1)
            self.assertEqual(len(retrieval.chunks(("memory", "focus"))), 2)

    def test_build_index_and_stats(self):
        with mock.patch.object(retrieval, "_memory_chunks",
                               return_value=[chunk("a"), chunk("b")]), \
             mock.patch.object(retrieval, "_focus_chunks", return_value=[]):
            r = retrieval.build_index()
            self.assertEqual(r["indexed"], 2)
            self.assertEqual(retrieval.index_stats()["indexed"], 2)


class TestQuery(unittest.TestCase):
    DOCS = [
        chunk("heap memory leak in the C++ build", ts=NOW - 1 * DAY, cid="a"),
        chunk("how to bake sourdough bread at home", ts=NOW - 1 * DAY, cid="b"),
        chunk("the router chooses a backend per level", ts=NOW - 1 * DAY, cid="c"),
        chunk("memory leak reproducer needed urgently", ts=NOW - 200 * DAY, cid="d"),
    ]

    def test_top_k(self):
        out = retrieval.query("heap memory leak", top_k=2, chunks_=self.DOCS,
                              recency_weight=0.0, now=NOW)
        self.assertEqual(len(out), 2)
        self.assertGreaterEqual(out[0]["score"], out[1]["score"])

    def test_relevance_orders(self):
        out = retrieval.query("heap memory leak c++", top_k=4, chunks_=self.DOCS,
                              recency_weight=0.0, now=NOW)
        self.assertTrue(out[0]["text"].startswith("heap memory leak"))
        self.assertEqual(out[0]["source"], "memory")

    def test_recency_weighting_prefers_recent(self):
        docs = [chunk("identical text here", ts=NOW - 300 * DAY, cid="old"),
                chunk("identical text here", ts=NOW - 1 * DAY, cid="new")]
        out = retrieval.query("identical text here", top_k=2, chunks_=docs,
                              recency_weight=1.0, now=NOW)
        self.assertEqual(out[0]["id"], "new")
        self.assertGreater(out[0]["recency"], out[1]["recency"])

    def test_zero_recency_weight_ignores_age(self):
        docs = [chunk("same words exactly", ts=NOW - 300 * DAY, cid="old"),
                chunk("same words exactly", ts=NOW - 1 * DAY, cid="new")]
        out = retrieval.query("same words exactly", top_k=2, chunks_=docs,
                              recency_weight=0.0, now=NOW)
        # equal relevance -> stable order preserved (no recency effect)
        self.assertEqual([r["id"] for r in out], ["old", "new"])

    def test_empty_index(self):
        self.assertEqual(retrieval.query("anything", chunks_=[], now=NOW), [])

    def test_recency_helper(self):
        self.assertAlmostEqual(retrieval._recency(NOW, NOW, 30.0), 1.0)
        self.assertLess(retrieval._recency(NOW - 30 * DAY, NOW, 30.0), 0.51)
        self.assertEqual(retrieval._recency(0, NOW, 30.0), 0.0)

    def test_result_shape(self):
        out = retrieval.query("heap memory leak", top_k=1, chunks_=self.DOCS, now=NOW)
        for k in ("text", "kind", "source", "id", "ts", "relevance", "recency", "score"):
            self.assertIn(k, out[0])


class TestOfflineFallback(unittest.TestCase):
    def test_embed_falls_back_to_hash_vectors(self):
        from jev import backends
        with mock.patch.object(backends.EmbeddingBackend, "healthy", return_value=False):
            vecs = retrieval.embed(["hello world", "goodbye"])
        self.assertEqual(len(vecs), 2)
        self.assertEqual(len(vecs[0]), retrieval._DIM)

    def test_query_works_without_embeddings(self):
        from jev import backends
        with mock.patch.object(backends.EmbeddingBackend, "healthy", return_value=False):
            out = retrieval.query("heap leak", top_k=1,
                                  chunks_=TestQuery.DOCS, recency_weight=0.0, now=NOW)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["text"].startswith("heap memory leak"))


if __name__ == "__main__":
    unittest.main()
