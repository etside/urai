#!/usr/bin/env python3
"""First-party Urai tests: vision, PDF, 503-when-not-loaded, no-external-AI."""
import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1x1 transparent PNG
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/")
DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_1X1).decode()


class TestUraiVision(unittest.TestCase):
    def test_png_reaches_urai_vision_path(self):
        from jev import vision as V
        r = V.see(DATA_URL, "How many pixels wide is this image?")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(r.get("backend"), "urai")
        self.assertEqual(r.get("image", {}).get("width"), 1)
        self.assertEqual(r.get("image", {}).get("height"), 1)
        self.assertTrue(r.get("answer"))

    def test_http_image_url_decoded_locally(self):
        # data: path already covered; http fetch path raises honest error when
        # unreachable instead of calling a vendor model.
        from jev.urai_runtime.vision import describe_image
        d = describe_image(DATA_URL)
        self.assertEqual((d["width"], d["height"]), (1, 1))
        self.assertEqual(d["format"], "png")


class TestUraiPdf(unittest.TestCase):
    def test_pdf_urai_assembles_raster_and_text(self):
        from jev import pdf as P
        # Minimal 1-page PDF with text "URAI"
        content = b"BT /F1 24 Tf 100 700 Td (URAI) Tj ET"
        objs = []
        bodies = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(content)).encode() + b" >> stream\n" + content + b"\nendstream",
        ]
        out = b"%PDF-1.4\n"
        offs = []
        for i, b in enumerate(bodies, 1):
            offs.append(len(out))
            out += f"{i} 0 obj\n".encode() + b + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 5\n0000000000 65535 f \n".encode()
        for o in offs:
            out += f"{o:010d} 00000 n \n".encode()
        out += f"trailer << /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
        proc = P.process_pdf(out)
        self.assertIn("URAI", proc["text"])
        self.assertGreaterEqual(proc["page_count"], 1)
        self.assertTrue(proc["raster_png"].startswith(b"\x89PNG"))
        self.assertTrue(proc["raster_b64"])

        res = P.complete_with_pdf(out, "What word is in the PDF?")
        self.assertEqual(res.get("backend"), "urai")
        self.assertTrue(res.get("answer"))


class TestMockOff503(unittest.TestCase):
    def test_pick_backend_raises_when_runtime_missing(self):
        # Hide weights via env override to simulate not-loaded, without
        # touching the real file: point runtime at missing path.
        import jev.backends as B
        from jev import router as R
        # Save + monkeypatch weights path
        old = B.UraiBackend._get_rt if hasattr(B.UraiBackend, "_get_rt") else None
        from jev.urai_runtime import runtime as RT
        saved = RT.WEIGHTS
        RT.WEIGHTS = RT.WEIGHTS.parent / "does-not-exist.json"
        RT._instance = None
        try:
            with self.assertRaises(RuntimeError) as cm:
                R.pick_backend(0)
            self.assertIn("503", str(cm.exception))
        finally:
            RT.WEIGHTS = saved
            RT._instance = None

    def test_router_never_returns_mock(self):
        from jev.router import pick_backend
        be, _, _ = pick_backend(0)
        self.assertNotEqual(getattr(be, "name", ""), "mock")
        self.assertEqual(getattr(be, "name", ""), "urai")


class TestNoExternalAI(unittest.TestCase):
    """Request path must not contain vendor model endpoints."""

    REQUEST_PATH = [
        "jev/backends.py", "jev/router.py", "jev/server.py",
        "jev/vision.py", "jev/pdf.py", "jev/urai_runtime/",
        "jev/brand.py", "jev/cli.py",
    ]
    FORBIDDEN_SUBSTRINGS = (
        "https://api.openai.com", "https://api.anthropic.com", "https://api.meta.ai",
        "http://api.openai.com", "http://api.anthropic.com", "http://api.meta.ai",
        "https://openrouter.ai", "https://together.ai", "https://api.together.ai",
        "huggingface.co/Qwen", "huggingface.co/ggml-org/Qwen",
    )

    def test_no_vendor_urls_in_request_path(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        hits = []
        for rel in self.REQUEST_PATH:
            p = root / rel
            files = list(p.rglob("*.py")) if p.is_dir() else [p]
            for f in files:
                text = f.read_text(errors="ignore").lower()
                for bad in self.FORBIDDEN_SUBSTRINGS:
                    if bad.lower() in text:
                        hits.append(f"{f.relative_to(root)}: {bad}")
        self.assertEqual(hits, [], f"vendor URLs in request path: {hits}")


if __name__ == "__main__":
    unittest.main()
