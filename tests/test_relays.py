"""Media relays (Seedream 4.0 image, Wan 3.0 video) + platform config.
HTTP is monkeypatched — no network."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from jev import platform, relays


class _Resp:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _make_urlopen(handlers):
    """handlers: list of (predicate, bytes) consumed in order (or a callable)."""
    calls = {"n": 0}

    def _urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = getattr(req, "get_method", lambda: "GET")()
        for pred, data in handlers:
            if pred(url, method):
                return _Resp(data)
        raise AssertionError(f"unexpected {method} {url}")

    return _urlopen


class PlatformConfig(unittest.TestCase):
    def test_endpoint_normalisation(self):
        self.assertEqual(platform.images_endpoint("https://ark.x.com"),
                         "https://ark.x.com/api/v3/images/generations")
        self.assertEqual(platform.images_endpoint("https://ark.x.com/api/v3"),
                         "https://ark.x.com/api/v3/images/generations")

    def test_wan_endpoints(self):
        self.assertIn("/api/v1/services/aigc/video-generation/video-synthesis",
                      platform.wan_endpoint("https://dash.example.com"))
        self.assertTrue(platform.wan_task_endpoint("https://dash.example.com", "t1")
                        .endswith("/api/v1/tasks/t1"))

    def test_env_overrides(self):
        os.environ["ARK_API_KEY"] = "k"
        os.environ["ARK_IMAGE_MODEL"] = "seedream-test"
        try:
            cfg = platform.image_cfg()
            self.assertEqual(cfg["api_key"], "k")
            self.assertEqual(cfg["model"], "seedream-test")
        finally:
            os.environ.pop("ARK_API_KEY", None)
            os.environ.pop("ARK_IMAGE_MODEL", None)


class Seedream(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._root = relays.ROOT
        relays.ROOT = Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in
                       ("ARK_API_KEY", "ARK_BASE", "ARK_IMAGE_MODEL")}

    def tearDown(self):
        relays.ROOT = self._root
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_missing_key_is_honest(self):
        os.environ.pop("ARK_API_KEY", None)
        r = relays.seedream_images("a cat")
        self.assertFalse(r["ok"])
        self.assertFalse(r["configured"])

    def test_url_result_is_persisted(self):
        os.environ["ARK_API_KEY"] = "k"
        img_bytes = b"\x89PNG\r\n\x1a\n-fake"
        relays.urllib.request.urlopen = _make_urlopen([
            (lambda u, m: m == "POST" and "images/generations" in u,
             json.dumps({"data": [{"url": "https://cdn.example/i.png"}]}).encode()),
            (lambda u, m: "cdn.example" in u, img_bytes),
        ])
        r = relays.seedream_images("a cat", size="1K")
        self.assertTrue(r["ok"])
        self.assertEqual(r["provider"], "seedream4")
        self.assertTrue(Path(r["path"]).is_file())
        self.assertEqual(Path(r["path"]).read_bytes(), img_bytes)

    def test_b64_result_decodes(self):
        os.environ["ARK_API_KEY"] = "k"
        b64 = base64.b64encode(b"PNGDATA").decode()
        relays.urllib.request.urlopen = _make_urlopen([
            (lambda u, m: "images/generations" in u,
             json.dumps({"data": [{"b64_json": b64}]}).encode()),
        ])
        r = relays.seedream_images("a cat", response_format="b64_json")
        self.assertTrue(r["ok"])
        self.assertEqual(Path(r["path"]).read_bytes(), b"PNGDATA")


class Wan(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._root = relays.ROOT
        relays.ROOT = Path(self._tmp.name)
        relays.POLL_INTERVAL_S = 0
        self._saved = os.environ.get("DASHSCOPE_API_KEY")

    def tearDown(self):
        relays.ROOT = self._root
        relays.POLL_INTERVAL_S = 5
        if self._saved is None:
            os.environ.pop("DASHSCOPE_API_KEY", None)
        else:
            os.environ["DASHSCOPE_API_KEY"] = self._saved
        self._tmp.cleanup()

    def test_missing_key_is_honest(self):
        os.environ.pop("DASHSCOPE_API_KEY", None)
        r = relays.wan_video("a dog")
        self.assertFalse(r["ok"])
        self.assertFalse(r["configured"])

    def test_async_success_persists(self):
        os.environ["DASHSCOPE_API_KEY"] = "k"
        mp4 = b"\x00\x00\x00\x18ftypmp42-fake"
        relays.urllib.request.urlopen = _make_urlopen([
            (lambda u, m: m == "POST" and "video-synthesis" in u,
             json.dumps({"output": {"task_id": "task-1"}}).encode()),
            (lambda u, m: m == "GET" and u.endswith("/api/v1/tasks/task-1"),
             json.dumps({"output": {"task_status": "SUCCEEDED",
                                    "video_url": "https://cdn.example/v.mp4"}}).encode()),
            (lambda u, m: "cdn.example" in u, mp4),
        ])
        r = relays.wan_video("a dog", duration=5)
        self.assertTrue(r["ok"])
        self.assertEqual(r["provider"], "wan3")
        self.assertTrue(Path(r["path"]).read_bytes() == mp4)

    def test_async_failure_surfaces(self):
        os.environ["DASHSCOPE_API_KEY"] = "k"
        relays.urllib.request.urlopen = _make_urlopen([
            (lambda u, m: m == "POST" and "video-synthesis" in u,
             json.dumps({"output": {"task_id": "t2"}}).encode()),
            (lambda u, m: m == "GET" and u.endswith("/api/v1/tasks/t2"),
             json.dumps({"output": {"task_status": "FAILED",
                                    "message": "bad prompt"}}).encode()),
        ])
        r = relays.wan_video("nope")
        self.assertFalse(r["ok"])
        self.assertIn("FAILED", r["error"])


if __name__ == "__main__":
    unittest.main()
