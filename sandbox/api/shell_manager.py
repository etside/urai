"""Shell session manager for the sandbox API.

Manages named shell sessions backed by a bash subprocess.
stdout/stderr are captured into a ring buffer (deque) per session.
"""

import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShellSession:
    id: str
    process: subprocess.Popen
    buffer: deque = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _reader: Optional[threading.Thread] = None

    def _read_loop(self) -> None:
        """Background thread: read lines from the process stdout into the ring buffer."""
        try:
            for line in self.process.stdout:
                with self._lock:
                    self.buffer.append(line)
        except Exception:
            pass

    def start_reader(self) -> None:
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def send(self, cmd: str) -> None:
        """Write a command line to the shell stdin."""
        if self.process.poll() is not None:
            raise RuntimeError(f"shell session {self.id!r} is no longer running")
        line = cmd if cmd.endswith("\n") else cmd + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

    def read_output(self, since_line: int = 0) -> list:
        """Return buffered lines starting from since_line index."""
        with self._lock:
            lines = list(self.buffer)
        return lines[since_line:]

    def kill(self) -> None:
        """Terminate the shell process."""
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


class ShellManager:
    """Create and manage named shell sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, ShellSession] = {}
        self._lock = threading.Lock()

    def create_session(self, session_id: str) -> ShellSession:
        """Create a new bash session (or return existing one)."""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]
            proc = subprocess.Popen(
                ["bash"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            session = ShellSession(id=session_id, process=proc)
            session.start_reader()
            self._sessions[session_id] = session
            return session

    def get_session(self, session_id: str) -> Optional[ShellSession]:
        return self._sessions.get(session_id)

    def get_or_create(self, session_id: str) -> ShellSession:
        session = self.get_session(session_id)
        if session is None:
            session = self.create_session(session_id)
        return session

    def send(self, session_id: str, cmd: str) -> None:
        session = self.get_or_create(session_id)
        session.send(cmd)

    def read_output(self, session_id: str, since_line: int = 0) -> list:
        session = self.get_or_create(session_id)
        return session.read_output(since_line)

    def kill(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            session.kill()

    def exec(self, session_id: str, cmd: str) -> dict:
        """Run a command synchronously and return output + exit code."""
        import subprocess as _sp
        try:
            result = _sp.run(
                ["bash", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout + result.stderr
            return {"ok": True, "output": output, "exit_code": result.returncode}
        except _sp.TimeoutExpired:
            return {"ok": False, "output": "", "exit_code": -1, "error": "timeout"}
        except Exception as e:
            return {"ok": False, "output": "", "exit_code": -1, "error": str(e)}
