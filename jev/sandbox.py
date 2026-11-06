"""DockerSandbox: create/manage a per-session Docker sandbox container.

Uses only stdlib (subprocess + urllib.request) — no Docker SDK.
Construction is lazy: importing this module does not require Docker.
"""

import json
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional


class DockerSandbox:
    """Manages a single Docker container running the urai-sandbox image.

    Usage::

        sb = DockerSandbox("session-xyz")
        sb.create()
        sb.ensure_ready(timeout=30)
        result = sb.proxy_call("POST", "/api/v1/shell/exec",
                               json={"session_id": "default", "cmd": "echo hi"})
        sb.destroy()
    """

    IMAGE = "urai-sandbox:latest"

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.container_id: Optional[str] = None
        self._api_port: Optional[int] = None
        self._debug_port: Optional[int] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create(self) -> str:
        """Start the sandbox container and return its container ID."""
        name = f"urai-sandbox-{self.session_id}"
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", name,
                "-p", "0:8080",
                "-p", "0:9222",
                self.IMAGE,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker run failed: {result.stderr.strip()}"
            )
        self.container_id = result.stdout.strip()
        self._api_port = self._resolve_port(8080)
        self._debug_port = self._resolve_port(9222)
        return self.container_id

    def _resolve_port(self, container_port: int) -> int:
        """Resolve the host-side port mapped to container_port."""
        result = subprocess.run(
            ["docker", "port", self.container_id, str(container_port)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"docker port failed: {result.stderr.strip()}"
            )
        # Output format: "0.0.0.0:PORT" or ":::PORT"
        line = result.stdout.strip().splitlines()[0]
        return int(line.rsplit(":", 1)[-1])

    def ensure_ready(self, timeout: float = 30) -> None:
        """Poll /api/v1/supervisor/status until all programs are running."""
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            try:
                data = self.proxy_call("GET", "/api/v1/supervisor/status")
                programs = data.get("programs", [])
                if programs and all(p["running"] for p in programs):
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(1.0)
        raise TimeoutError(
            f"sandbox {self.session_id!r} not ready after {timeout}s; "
            f"last error: {last_error}"
        )

    def destroy(self) -> None:
        """Force-remove the container."""
        if not self.container_id:
            return
        subprocess.run(
            ["docker", "rm", "-f", self.container_id],
            capture_output=True,
            timeout=30,
        )
        self.container_id = None
        self._api_port = None
        self._debug_port = None

    # ------------------------------------------------------------------
    # HTTP proxy
    # ------------------------------------------------------------------

    def proxy_call(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> dict:
        """Forward an HTTP call to the sandbox API.

        Keyword args:
            json  – dict to send as JSON body (for POST).
            params – dict of query-string parameters (for GET).
        """
        if self._api_port is None:
            raise RuntimeError("sandbox not started; call create() first")

        base_url = f"http://127.0.0.1:{self._api_port}"
        url = base_url + path

        # Append query params
        params = kwargs.get("params")
        if params:
            qs = "&".join(
                f"{urllib.parse.quote(str(k))}={urllib.parse.quote(str(v))}"
                for k, v in params.items()
            )
            url = url + "?" + qs

        body: Optional[bytes] = None
        headers: dict = {}

        json_body = kwargs.get("json")
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return json.loads(raw.decode("utf-8"))
            except Exception:
                raise RuntimeError(f"HTTP {exc.code}: {raw[:200]!r}") from exc


# Fix missing import that would only surface at runtime
import urllib.parse  # noqa: E402  (needed by proxy_call)
