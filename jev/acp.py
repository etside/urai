"""
urai_acp.py — Agent Client Protocol (ACP) server for Urai.

This module implements the Agent Client Protocol so that OpenLive
(katipally/openlive) can connect to Urai as a voice-capable agent.

ACP is JSON-RPC 2.0 transported over:
  • stdio  (default) — OpenLive launches `python -m jev.acp` as a child process
  • TCP    — `serve_acp(port=9876)` for LAN/remote connections

Protocol overview
-----------------
Request  → {"jsonrpc":"2.0","method":"<method>","params":{...},"id":<int|str>}
Response → {"jsonrpc":"2.0","result":{...},"id":<int|str>}
Error    → {"jsonrpc":"2.0","error":{"code":<int>,"message":"<str>"},"id":<int|str|null>}

Supported methods
-----------------
ping          params: {}
              result: {"pong": true, "agent": "urai", "ts": <epoch>}

status        params: {}
              result: {"agent": "urai", "version": "...", "session_count": <n>}

get_tools     params: {}
              result: {"tools": [{"name":..., "description":...}, ...]}

chat          params: {"message": str, "session_id"?: str, "context"?: [...]}
              result: {"answer": str, "agent": str, "elapsed_s": float,
                       "session_id": str, "tool_calls": [...]}

stream_chat   params: same as chat
              result: stream of {"chunk": str, "done": bool} objects
              (each emitted as a separate JSON-RPC notification with method
              "stream_chunk" and id matching the original request; final chunk
              has done=true plus the full "answer" field)

interrupt     params: {"session_id": str}
              result: {"interrupted": bool}

JSON-RPC error codes
--------------------
-32700  Parse error
-32600  Invalid request
-32601  Method not found
-32602  Invalid params
-32603  Internal error

Usage
-----
    # stdio mode (default — used by OpenLive)
    python -m jev.acp

    # TCP mode
    python -m jev.acp --port 9876

    # Programmatic
    from jev.acp import serve_acp
    serve_acp(port=9876)   # blocks; call in a thread for embedding
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import socket
import sys
import threading
import time
import traceback
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

log = logging.getLogger("urai.acp")

# ---------------------------------------------------------------------------
# Version / metadata
# ---------------------------------------------------------------------------

ACP_VERSION = "1.0.0"
AGENT_NAME = "urai"
AGENT_DESCRIPTION = (
    "Urai — a voice-capable AI assistant. "
    "Connects to OpenLive via the Agent Client Protocol (ACP/JSON-RPC 2.0)."
)

# ---------------------------------------------------------------------------
# Try to import the real Urai agent loop
# ---------------------------------------------------------------------------

try:
    from jev.agent import run as _agent_run  # type: ignore
    _AGENT_AVAILABLE = True
except ImportError:
    _AGENT_AVAILABLE = False
    _agent_run = None  # type: ignore

try:
    from jev.agent import stream_run as _agent_stream_run  # type: ignore
    _AGENT_STREAM_AVAILABLE = True
except ImportError:
    _AGENT_STREAM_AVAILABLE = False
    _agent_stream_run = None  # type: ignore

try:
    from jev.agent import list_tools as _list_tools  # type: ignore
    _TOOLS_AVAILABLE = True
except ImportError:
    _TOOLS_AVAILABLE = False
    _list_tools = None  # type: ignore

# ---------------------------------------------------------------------------
# Session registry
# ---------------------------------------------------------------------------

_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def _get_or_create_session(session_id: Optional[str]) -> str:
    sid = session_id or str(uuid.uuid4())
    with _sessions_lock:
        if sid not in _sessions:
            _sessions[sid] = {
                "session_id": sid,
                "created_at": time.time(),
                "last_active": time.time(),
                "interrupted": False,
                "history": [],
            }
        else:
            _sessions[sid]["last_active"] = time.time()
    return sid


def _interrupt_session(session_id: str) -> bool:
    with _sessions_lock:
        if session_id not in _sessions:
            return False
        _sessions[session_id]["interrupted"] = True
    return True


def _session_count() -> int:
    with _sessions_lock:
        return len(_sessions)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

JSONRPC = "2.0"

def _ok(result: Any, req_id: Any) -> dict:
    return {"jsonrpc": JSONRPC, "result": result, "id": req_id}


def _err(code: int, message: str, req_id: Any, data: Any = None) -> dict:
    error: dict = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC, "error": error, "id": req_id}


def _notification(method: str, params: dict) -> dict:
    """A JSON-RPC notification (no id field → no response expected)."""
    return {"jsonrpc": JSONRPC, "method": method, "params": params}


def _encode(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------

def _handle_ping(_params: dict, _req_id: Any) -> dict:
    return _ok({"pong": True, "agent": AGENT_NAME, "ts": time.time()}, _req_id)


def _handle_status(_params: dict, _req_id: Any) -> dict:
    return _ok(
        {
            "agent": AGENT_NAME,
            "version": ACP_VERSION,
            "session_count": _session_count(),
            "agent_available": _AGENT_AVAILABLE,
            "stream_available": _AGENT_STREAM_AVAILABLE,
        },
        _req_id,
    )


def _handle_get_tools(_params: dict, _req_id: Any) -> dict:
    if _TOOLS_AVAILABLE and _list_tools:
        try:
            tools = _list_tools()
        except Exception:
            tools = []
    else:
        # Stub tool list when jev.agent is not installed
        tools = [
            {"name": "browse", "description": "Browse a URL and return page content"},
            {"name": "search", "description": "Search the web for a query"},
            {"name": "recall", "description": "Retrieve from Urai's long-term memory"},
            {"name": "remember", "description": "Store a fact in Urai's long-term memory"},
        ]
    return _ok({"tools": tools}, _req_id)


def _run_agent(
    message: str,
    session_id: str,
    context: Optional[List[dict]] = None,
) -> Tuple[str, str, List[dict]]:
    """
    Run the Urai agent loop synchronously.  Returns (answer, agent_name, tool_calls).
    Falls back to a stub response when the real agent is unavailable.
    """
    with _sessions_lock:
        history = list(_sessions.get(session_id, {}).get("history", []))

    if _AGENT_AVAILABLE and _agent_run:
        try:
            result = _agent_run(
                message=message,
                session_id=session_id,
                history=history,
                context=context or [],
            )
            answer = result.get("answer", "")
            agent = result.get("agent", AGENT_NAME)
            tool_calls = result.get("tool_calls", [])
        except Exception as exc:
            log.exception("Agent error for session %s", session_id)
            answer = f"[Agent error: {exc}]"
            agent = AGENT_NAME
            tool_calls = []
    else:
        # Stub response
        answer = (
            f"(Urai agent not loaded — stub reply) "
            f"You said: {message!r}"
        )
        agent = AGENT_NAME
        tool_calls = []

    # Update history
    with _sessions_lock:
        if session_id in _sessions:
            _sessions[session_id]["history"].append({"role": "user", "content": message})
            _sessions[session_id]["history"].append({"role": "assistant", "content": answer})

    return answer, agent, tool_calls


def _handle_chat(params: dict, req_id: Any) -> dict:
    message = params.get("message")
    if not isinstance(message, str) or not message.strip():
        return _err(-32602, "Invalid params: 'message' must be a non-empty string", req_id)

    session_id = _get_or_create_session(params.get("session_id"))
    context = params.get("context")

    t0 = time.time()
    answer, agent, tool_calls = _run_agent(message, session_id, context)
    elapsed = time.time() - t0

    return _ok(
        {
            "answer": answer,
            "agent": agent,
            "elapsed_s": round(elapsed, 3),
            "session_id": session_id,
            "tool_calls": tool_calls,
        },
        req_id,
    )


def _handle_interrupt(params: dict, req_id: Any) -> dict:
    session_id = params.get("session_id")
    if not session_id:
        return _err(-32602, "Invalid params: 'session_id' required", req_id)

    interrupted = _interrupt_session(session_id)
    # Also interrupt any running browser sessions with the same ID
    try:
        from urai_browser2 import interrupt as browser_interrupt  # type: ignore
        browser_interrupt(session_id)
    except Exception:
        pass

    return _ok({"interrupted": interrupted, "session_id": session_id}, req_id)


# ---------------------------------------------------------------------------
# Streaming handler
# ---------------------------------------------------------------------------

class _StreamWriter:
    """
    Wraps a write-callable and emits JSON-RPC notifications for each chunk.
    The caller is responsible for flushing / framing.
    """
    def __init__(self, write_fn: Callable[[bytes], None], req_id: Any):
        self._write = write_fn
        self._req_id = req_id
        self._chunks: List[str] = []

    def emit(self, chunk: str, done: bool = False, extra: Optional[dict] = None) -> None:
        payload: dict = {
            "chunk": chunk,
            "done": done,
            "id": self._req_id,
        }
        if extra:
            payload.update(extra)
        notification = _notification("stream_chunk", payload)
        self._write(_encode(notification))
        if chunk:
            self._chunks.append(chunk)

    def full_answer(self) -> str:
        return "".join(self._chunks)


def _handle_stream_chat(params: dict, req_id: Any, write_fn: Callable[[bytes], None]) -> dict:
    """
    Handle stream_chat.  Emits a series of 'stream_chunk' notifications via
    write_fn, then returns a final result dict (for the caller to send as a
    normal JSON-RPC response).
    """
    message = params.get("message")
    if not isinstance(message, str) or not message.strip():
        return _err(-32602, "Invalid params: 'message' must be a non-empty string", req_id)

    session_id = _get_or_create_session(params.get("session_id"))
    context = params.get("context")
    writer = _StreamWriter(write_fn, req_id)

    t0 = time.time()

    if _AGENT_STREAM_AVAILABLE and _agent_stream_run:
        try:
            with _sessions_lock:
                history = list(_sessions.get(session_id, {}).get("history", []))

            gen: Iterator[dict] = _agent_stream_run(
                message=message,
                session_id=session_id,
                history=history,
                context=context or [],
            )
            agent = AGENT_NAME
            tool_calls: List[dict] = []
            for event in gen:
                with _sessions_lock:
                    interrupted = _sessions.get(session_id, {}).get("interrupted", False)
                if interrupted:
                    writer.emit("[interrupted]", done=True)
                    break
                chunk = event.get("chunk", "")
                is_done = event.get("done", False)
                if "tool_call" in event:
                    tool_calls.append(event["tool_call"])
                if event.get("agent"):
                    agent = event["agent"]
                if is_done:
                    writer.emit(chunk, done=True, extra={"tool_calls": tool_calls})
                    break
                writer.emit(chunk)
        except Exception as exc:
            log.exception("stream_run error")
            writer.emit(f"[error: {exc}]", done=True)
            agent = AGENT_NAME
            tool_calls = []
    else:
        # Stub: split stub answer into word-by-word chunks to simulate streaming
        answer, agent, tool_calls = _run_agent(message, session_id, context)
        words = answer.split()
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            time.sleep(0.02)  # simulate token delay
            writer.emit(chunk, done=(i == len(words) - 1))

    elapsed = time.time() - t0

    # Update history if streaming path (non-stub) was used
    if _AGENT_STREAM_AVAILABLE:
        full = writer.full_answer()
        with _sessions_lock:
            if session_id in _sessions:
                _sessions[session_id]["history"].append({"role": "user", "content": message})
                _sessions[session_id]["history"].append({"role": "assistant", "content": full})

    return _ok(
        {
            "answer": writer.full_answer(),
            "agent": agent,
            "elapsed_s": round(elapsed, 3),
            "session_id": session_id,
            "tool_calls": tool_calls if _AGENT_STREAM_AVAILABLE else [],
        },
        req_id,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_METHODS: Dict[str, Callable] = {
    "ping": _handle_ping,
    "status": _handle_status,
    "get_tools": _handle_get_tools,
    "chat": _handle_chat,
    "interrupt": _handle_interrupt,
}


def dispatch(
    raw: str,
    write_fn: Callable[[bytes], None],
) -> Optional[dict]:
    """
    Parse and dispatch a single JSON-RPC request.

    *write_fn* is called for streaming notifications.
    Returns the final response dict (caller should serialise and send it),
    or None for JSON-RPC notifications (no id → no response).
    """
    try:
        req = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _err(-32700, f"Parse error: {exc}", None)

    if not isinstance(req, dict):
        return _err(-32600, "Invalid request: expected object", None)

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}

    if not isinstance(method, str):
        return _err(-32600, "Invalid request: 'method' must be a string", req_id)

    if not isinstance(params, dict):
        return _err(-32602, "Invalid params: must be an object", req_id)

    # stream_chat is special — needs write_fn for notifications
    if method == "stream_chat":
        try:
            return _handle_stream_chat(params, req_id, write_fn)
        except Exception as exc:
            log.exception("Unhandled error in stream_chat")
            return _err(-32603, f"Internal error: {exc}", req_id)

    handler = _METHODS.get(method)
    if handler is None:
        return _err(-32601, f"Method not found: {method!r}", req_id)

    try:
        return handler(params, req_id)
    except Exception as exc:
        log.exception("Unhandled error in method %s", method)
        return _err(-32603, f"Internal error: {exc}", req_id)


# ---------------------------------------------------------------------------
# ACPServer class
# ---------------------------------------------------------------------------

class ACPServer:
    """
    JSON-RPC 2.0 server for Urai.

    Reads newline-delimited JSON from *reader* and writes responses to
    *writer*.  Each request is dispatched to the appropriate handler.
    Concurrent requests are handled via an internal work queue backed by
    a thread pool.

    Parameters
    ----------
    reader : file-like  — source of incoming bytes (default: sys.stdin.buffer)
    writer : file-like  — sink for outgoing bytes  (default: sys.stdout.buffer)
    workers: int        — number of handler threads (default: 4)
    """

    def __init__(
        self,
        reader=None,
        writer=None,
        workers: int = 4,
    ):
        self._reader = reader or sys.stdin.buffer
        self._writer = writer or sys.stdout.buffer
        self._workers = workers
        self._queue: queue.Queue = queue.Queue()
        self._write_lock = threading.Lock()
        self._running = False

    # --- Low-level I/O ---

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            self._writer.write(data)
            self._writer.flush()

    # --- Worker thread ---

    def _worker(self) -> None:
        while True:
            raw = self._queue.get()
            if raw is None:  # shutdown sentinel
                self._queue.task_done()
                break
            try:
                response = dispatch(raw, self._write)
                if response is not None:
                    self._write(_encode(response))
            except Exception:
                log.exception("Worker error processing: %r", raw)
            finally:
                self._queue.task_done()

    # --- Main serve loop ---

    def serve(self) -> None:
        """Block and serve requests until EOF or KeyboardInterrupt."""
        self._running = True
        threads = []
        for _ in range(self._workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            threads.append(t)

        log.info(
            "ACPServer started (agent=%s version=%s workers=%d)",
            AGENT_NAME, ACP_VERSION, self._workers,
        )

        try:
            for raw_line in self._reader:
                line = raw_line.strip()
                if not line:
                    continue
                self._queue.put(line.decode("utf-8", errors="replace"))
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            # Send shutdown sentinels
            for _ in threads:
                self._queue.put(None)
            for t in threads:
                t.join(timeout=2)
            self._running = False
            log.info("ACPServer stopped")

    def serve_once(self, raw: str) -> Optional[str]:
        """
        Process a single request string synchronously (useful for testing).
        Returns the JSON-encoded response, or None for notifications.
        """
        chunks: List[bytes] = []
        response = dispatch(raw, lambda data: chunks.append(data))
        out = b"".join(chunks)
        if response is not None:
            out += _encode(response)
        return out.decode("utf-8") if out else None


# ---------------------------------------------------------------------------
# TCP mode
# ---------------------------------------------------------------------------

def _handle_tcp_client(conn: socket.socket, addr: Tuple) -> None:
    log.info("TCP client connected from %s", addr)
    fh_in = conn.makefile("rb")
    fh_out = conn.makefile("wb")
    server = ACPServer(reader=fh_in, writer=fh_out, workers=2)
    try:
        server.serve()
    finally:
        try:
            conn.close()
        except Exception:
            pass
        log.info("TCP client disconnected from %s", addr)


def _serve_tcp(port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.listen(5)
    log.info("ACP TCP server listening on port %d", port)
    try:
        while True:
            conn, addr = sock.accept()
            t = threading.Thread(
                target=_handle_tcp_client,
                args=(conn, addr),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# serve_acp — main entry point
# ---------------------------------------------------------------------------

def serve_acp(port: Optional[int] = None, workers: int = 4) -> None:
    """
    Start the ACP server.

    If *port* is given, listen on that TCP port (LAN/remote mode).
    Otherwise read from stdin / write to stdout (default for OpenLive).

    Blocks until the process is terminated.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,  # keep stderr clean from JSON-RPC traffic on stdout
    )

    if port is not None:
        _serve_tcp(port)
    else:
        server = ACPServer(workers=workers)
        server.serve()


# ---------------------------------------------------------------------------
# register_with_openlive
# ---------------------------------------------------------------------------

def register_with_openlive(
    port: Optional[int] = None,
    extra: Optional[dict] = None,
) -> str:
    """
    Write ~/.openlive/agents/urai.json so OpenLive discovers Urai automatically.

    The registration file tells OpenLive:
      - how to launch Urai (stdio command) or connect to it (TCP)
      - the agent's capabilities and ACP version

    Returns the path of the written file.
    """
    openlive_dir = os.path.join(os.path.expanduser("~"), ".openlive", "agents")
    os.makedirs(openlive_dir, exist_ok=True)

    launch_cmd = [sys.executable, "-m", "jev.acp"]
    if port:
        launch_cmd += ["--port", str(port)]

    registration: dict = {
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "acp_version": ACP_VERSION,
        "transport": "tcp" if port else "stdio",
        "launch_command": launch_cmd,
        "methods": list(_METHODS.keys()) + ["stream_chat"],
        "capabilities": {
            "voice": True,
            "streaming": True,
            "tools": True,
            "barge_in": True,
        },
        "registered_at": time.time(),
    }
    if port:
        registration["host"] = "127.0.0.1"
        registration["port"] = port
    if extra:
        registration.update(extra)

    path = os.path.join(openlive_dir, "urai.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(registration, fh, indent=2)

    log.info("Registered Urai with OpenLive at %s", path)
    return path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m jev.acp",
        description="Urai ACP server — Agent Client Protocol for OpenLive",
    )
    p.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="TCP port to listen on (default: stdio mode)",
    )
    p.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Number of handler threads (default: 4)",
    )
    p.add_argument(
        "--register",
        action="store_true",
        help="Write ~/.openlive/agents/urai.json and exit",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    return p


if __name__ == "__main__":
    parser = _build_arg_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.register:
        path = register_with_openlive(port=args.port)
        print(f"Registered: {path}", file=sys.stderr)
        sys.exit(0)

    serve_acp(port=args.port, workers=args.workers)
