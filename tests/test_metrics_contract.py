"""Phase 2 API-hardening unit tests: error contract, backends streaming,
metrics helpers. Pure/local — no model, no network."""
import json
import unittest

from jev import backends
from jev.server import _normalize_error, _prometheus_text, _metrics_snapshot, _with_cache


class ErrorContract(unittest.TestCase):
    def test_flat_error_is_normalized(self):
        out = _normalize_error({"error": "boom"}, 500)
        self.assertEqual(out["error"]["message"], "boom")
        self.assertEqual(out["error"]["type"], "server_error")
        self.assertEqual(out["error"]["code"], "server_error")

    def test_status_maps_to_type_and_code(self):
        self.assertEqual(_normalize_error({"error": "x"}, 404)["error"],
                         {"message": "x", "type": "invalid_request_error",
                          "code": "not_found"})
        self.assertEqual(_normalize_error({"error": "x"}, 401)["error"]["code"],
                         "invalid_api_key")
        self.assertEqual(_normalize_error({"error": "x"}, 403)["error"]["type"],
                         "auth_error")

    def test_explicit_code_wins(self):
        out = _normalize_error({"error": "x", "code": "custom"}, 400)
        self.assertEqual(out["error"]["code"], "custom")

    def test_already_nested_is_untouched(self):
        nested = {"error": {"message": "m", "type": "auth_error", "code": "forbidden"}}
        self.assertIs(_normalize_error(nested, 403), nested)

    def test_success_payload_untouched(self):
        ok = {"choices": [], "text": "hi"}
        self.assertIs(_normalize_error(ok, 200), ok)


class BackendStreaming(unittest.TestCase):
    def test_mock_stream_yields_multiple_pieces(self):
        pieces = list(backends.MockBackend().stream(
            [{"role": "user", "content": "hi"}], max_tokens=8))
        self.assertGreaterEqual(len(pieces), 2)
        self.assertTrue(all(isinstance(p, str) for p in pieces))

    def test_mock_stream_reassembles_to_completion(self):
        be = backends.MockBackend()
        msgs = [{"role": "user", "content": "hello"}]
        joined = "".join(be.stream(msgs))
        self.assertEqual(joined, be.complete(msgs)["content"])

    def test_base_stream_falls_back_to_chunking(self):
        class One(backends.Backend):
            name = "one"

            def complete(self, messages, max_tokens=256, temperature=0.2):
                return {"content": "alpha beta gamma"}

        out = list(One().stream([{"role": "user", "content": "x"}]))
        self.assertGreaterEqual(len(out), 2)
        self.assertEqual("".join(out), "alpha beta gamma")


class MetricsHelpers(unittest.TestCase):
    def test_snapshot_has_core_sections(self):
        snap = _metrics_snapshot()
        for key in ("uptime_seconds", "env", "requests", "tokens", "cache"):
            self.assertIn(key, snap)
        self.assertIsInstance(snap["uptime_seconds"], (int, float))

    def test_prometheus_text_has_metric_names(self):
        text = _prometheus_text(_metrics_snapshot())
        for name in ("urai_uptime_seconds", "urai_requests_total",
                     "urai_cache_hits_total", "urai_local_llama_up"):
            self.assertIn(name, text)
        self.assertTrue(text.endswith("\n"))

    def test_with_cache_folds_hit_info(self):
        meta = _with_cache({"nlp": {}}, {"cached": True, "cache_hit": {"similarity": 0.99}})
        self.assertTrue(meta["cached"])
        self.assertIn("cache_hit", meta)
        self.assertIn("nlp", meta)

    def test_with_cache_noop_without_flag(self):
        self.assertEqual(_with_cache({"a": 1}, {"content": "x"}), {"a": 1})


if __name__ == "__main__":
    unittest.main()
