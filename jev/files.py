#!/usr/bin/env python3
"""File upload handling with PDF text extraction.

Uses PyMuPDF (fitz) for PDF text extraction — Apache 2.0, production-grade.
If pymupdf is not installed, extraction returns a clear error message.

Uploaded files are saved to data/uploads/ with a UUID prefix.
Metadata is stored in data/uploads/index.json for listing.
"""
from __future__ import annotations
import json
import os
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPLOADS_DIR = ROOT / "data" / "uploads"
INDEX_FILE = UPLOADS_DIR / "index.json"


def _ensure_dir():
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _load_index() -> list:
    _ensure_dir()
    try:
        return json.loads(INDEX_FILE.read_text())
    except Exception:
        return []


def _save_index(items: list):
    _ensure_dir()
    INDEX_FILE.write_text(json.dumps(items, indent=2, ensure_ascii=False))


def extract_pdf_text(path_or_bytes) -> dict:
    """Extract text from a PDF file or bytes.

    Returns {ok, text, pages, title} on success, or
    {ok: False, error: ...} if pymupdf is missing or the file is invalid.
    """
    try:
        import fitz
    except ImportError:
        return {"ok": False,
                "error": "pymupdf not installed; pip install pymupdf"}
    try:
        if isinstance(path_or_bytes, (bytes, bytearray)):
            doc = fitz.open(stream=bytes(path_or_bytes), filetype="pdf")
        else:
            doc = fitz.open(str(path_or_bytes))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        text = "\n".join(text_parts).strip()
        return {
            "ok": True,
            "text": text,
            "pages": doc.page_count,
            "title": doc.metadata.get("title", "") if hasattr(doc, "metadata") else "",
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def save_upload(filename: str, data_bytes: bytes) -> dict:
    """Save uploaded file, extract text if PDF, return metadata."""
    _ensure_dir()
    file_id = uuid.uuid4().hex[:12]
    safe_name = os.path.basename(filename)[:200]
    local_path = UPLOADS_DIR / f"{file_id}-{safe_name}"
    local_path.write_bytes(data_bytes)

    result = {
        "id": file_id,
        "name": safe_name,
        "size": len(data_bytes),
        "uploaded_at": time.time(),
        "pages": 0,
        "text_preview": "",
        "path": str(local_path),
    }

    # If PDF, extract text
    if safe_name.lower().endswith(".pdf"):
        ext = extract_pdf_text(data_bytes)
        if ext.get("ok"):
            result["pages"] = ext["pages"]
            result["text_preview"] = ext["text"][:500]
            result["full_text"] = ext["text"]
            result["title"] = ext.get("title", "")
        else:
            result["pdf_error"] = ext.get("error", "")

    # Update index
    items = _load_index()
    items.append({k: v for k, v in result.items() if k != "full_text"})
    _save_index(items)

    return result


def list_files() -> list:
    return _load_index()


def get_file_text(file_id: str) -> str:
    """Return extracted text for a file_id, or empty string if not found."""
    items = _load_index()
    for item in items:
        if item.get("id") == file_id:
            # Re-read from the stored file if it's a PDF
            path = item.get("path", "")
            if path and os.path.basename(path).lower().endswith(".pdf"):
                try:
                    ext = extract_pdf_text(path)
                    return ext.get("text", "") if ext.get("ok") else ""
                except Exception:
                    return ""
            return item.get("text_preview", "")
    return ""
