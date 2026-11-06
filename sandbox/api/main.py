"""Sandbox FastAPI application.

Exposes HTTP endpoints for shell management, file operations,
and supervisor status used by the DockerSandbox host-side proxy.
"""

import glob
import os
import re
import subprocess
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from shell_manager import ShellManager

app = FastAPI(title="urai-sandbox-api", version="1.0.0")
_shells = ShellManager()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ShellExecRequest(BaseModel):
    session_id: str = "default"
    cmd: str


class ShellSessionRequest(BaseModel):
    session_id: str = "default"


class ShellWaitRequest(BaseModel):
    session_id: str = "default"
    timeout: Optional[float] = 10.0


class ShellWriteRequest(BaseModel):
    session_id: str = "default"
    text: str


class FileReadRequest(BaseModel):
    path: str


class FileWriteRequest(BaseModel):
    path: str
    content: str = ""


class FileReplaceRequest(BaseModel):
    path: str
    old: str
    new: str = ""


class FileSearchRequest(BaseModel):
    path: str
    pattern: str


class FileFindRequest(BaseModel):
    path: str
    name: str


# ---------------------------------------------------------------------------
# Shell routes
# ---------------------------------------------------------------------------

@app.post("/api/v1/shell/exec")
def shell_exec(req: ShellExecRequest) -> dict:
    """Run a command synchronously in an isolated bash subprocess."""
    result = _shells.exec(req.session_id, req.cmd)
    return result


@app.post("/api/v1/shell/view")
def shell_view(req: ShellSessionRequest) -> dict:
    """Return current ring-buffer contents for a session."""
    lines = _shells.read_output(req.session_id, since_line=0)
    return {"ok": True, "lines": lines}


@app.post("/api/v1/shell/wait")
def shell_wait(req: ShellWaitRequest) -> dict:
    """Block until the shell session produces output or timeout elapses."""
    import time
    session = _shells.get_or_create(req.session_id)
    deadline = time.monotonic() + (req.timeout or 10.0)
    initial = len(list(session.buffer))
    while time.monotonic() < deadline:
        current = len(list(session.buffer))
        if current != initial:
            break
        time.sleep(0.1)
    return {"ok": True}


@app.post("/api/v1/shell/write")
def shell_write(req: ShellWriteRequest) -> dict:
    """Write text to the session's stdin (useful for interactive prompts)."""
    try:
        session = _shells.get_or_create(req.session_id)
        session.send(req.text)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/shell/kill")
def shell_kill(req: ShellSessionRequest) -> dict:
    """Terminate a named shell session."""
    _shells.kill(req.session_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# File routes
# ---------------------------------------------------------------------------

@app.post("/api/v1/file/read")
def file_read(req: FileReadRequest) -> dict:
    try:
        with open(req.path) as f:
            content = f.read()
        return {"ok": True, "content": content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/file/write")
def file_write(req: FileWriteRequest) -> dict:
    try:
        os.makedirs(os.path.dirname(os.path.abspath(req.path)), exist_ok=True)
        with open(req.path, "w") as f:
            f.write(req.content)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/file/replace")
def file_replace(req: FileReplaceRequest) -> dict:
    try:
        with open(req.path) as f:
            text = f.read()
        if req.old not in text:
            return {"ok": False, "error": "pattern not found"}
        text = text.replace(req.old, req.new, 1)
        with open(req.path, "w") as f:
            f.write(text)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/file/search")
def file_search(req: FileSearchRequest) -> dict:
    try:
        results = []
        pattern = re.compile(req.pattern)
        with open(req.path) as f:
            for lineno, line in enumerate(f, 1):
                if pattern.search(line):
                    results.append({"line": lineno, "text": line.rstrip()})
        return {"ok": True, "results": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/file/find")
def file_find(req: FileFindRequest) -> dict:
    try:
        matches = []
        for root, dirs, files in os.walk(req.path):
            for fname in files:
                if re.search(req.name, fname):
                    matches.append(os.path.join(root, fname))
        return {"ok": True, "files": matches}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/v1/file/upload")
async def file_upload(file: UploadFile = File(...), path: str = "/tmp") -> dict:
    try:
        dest = os.path.join(path, file.filename or "upload")
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        content = await file.read()
        with open(dest, "wb") as f:
            f.write(content)
        return {"ok": True, "path": dest}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/v1/file/download")
def file_download(path: str = Query(...)) -> FileResponse:
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


# ---------------------------------------------------------------------------
# Supervisor status
# ---------------------------------------------------------------------------

@app.get("/api/v1/supervisor/status")
def supervisor_status() -> dict:
    """Query supervisorctl for program status."""
    try:
        result = subprocess.run(
            ["supervisorctl", "-c", "/etc/supervisor/conf.d/supervisord.conf", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        programs = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                state = parts[1]
                programs.append({"name": name, "running": state == "RUNNING"})
        return {"ok": True, "programs": programs}
    except Exception as e:
        return {"ok": False, "programs": [], "error": str(e)}
