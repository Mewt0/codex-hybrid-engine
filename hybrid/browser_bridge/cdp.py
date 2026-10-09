"""Minimal Chrome DevTools Protocol client (stdlib only).

Used to drive a real Chrome instance over `--remote-debugging-port`:

    page = ChromePage.launch(profile_dir, port=9333)
    page.navigate("https://chatgpt.com/")
    print(page.eval("document.title"))

No third-party dependency: the WebSocket client below implements just the
handshake and text frames, which is all CDP needs.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


class CdpError(RuntimeError):
    pass


class WebSocket:
    """Tiny RFC6455 text client (no TLS: CDP is plain ws:// on localhost)."""

    def __init__(self, url: str, timeout: float = 30.0):
        parsed = urlparse(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise CdpError(f"Refusing non-local WebSocket target: {url}")
        self.timeout = timeout
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
        self.sock.settimeout(timeout)
        # Set when a frame was only partially read: the byte stream no longer
        # starts at a message boundary, so the socket must not be reused.
        self._desynchronised = False
        self._handshake(parsed)

    def _handshake(self, parsed) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = self._read_headers()
        if b"101" not in response.split(b"\r\n", 1)[0]:
            raise CdpError(f"WebSocket handshake failed: {response[:120]!r}")

    def _read_headers(self) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("Connection closed during handshake")
            data += chunk
        return data

    def send_text(self, text: str) -> None:
        payload = text.encode()
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        header += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        """Read one complete text message, joining continuation frames.

        RFC6455 allows a message to be split across frames; CDP *usually* sends
        one frame per message, but a large `Runtime.evaluate` reply can be
        fragmented, and returning only the first fragment produces a JSON parse
        error far away from the real cause. FIN is therefore honoured.
        """
        fragments: list[bytes] = []
        while True:
            fin, opcode, payload = self._recv_frame()
            if opcode == 0x8:
                raise CdpError("WebSocket closed by peer")
            if opcode == 0x9:
                self._send_control(0x8A, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                fragments = [payload]
            elif opcode == 0x0:
                if not fragments:
                    raise CdpError("WebSocket continuation frame without a start frame")
                fragments.append(payload)
            else:
                raise CdpError(f"Unsupported WebSocket opcode {opcode:#x}")
            if fin:
                return b"".join(fragments).decode("utf-8", errors="replace")

    def _send_control(self, opcode: int, payload: bytes = b"") -> None:
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        header = bytearray([0x80 | opcode])
        if len(payload) < 126:
            header.append(0x80 | len(payload))
        else:
            header.append(0x80 | 126)
            header += struct.pack(">H", len(payload))
        header += mask
        self.sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        first = self._recv_exact(2)
        fin = bool(first[0] & 0x80)
        opcode = first[0] & 0x0F
        masked = bool(first[1] & 0x80)
        length = first[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _recv_exact(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            try:
                chunk = self.sock.recv(count - len(data))
            except socket.timeout as exc:
                # The frame is now half-read: every later call on this socket
                # would decode garbage, so the connection is marked unusable.
                self._desynchronised = True
                raise CdpError(
                    f"Timed out reading from the DevTools socket ({count - len(data)} bytes pending)"
                ) from exc
            except OSError as exc:
                self._desynchronised = True
                raise CdpError(f"DevTools socket error: {exc}") from exc
            if not chunk:
                self._desynchronised = True
                raise CdpError("Connection closed")
            data += chunk
        return data

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class ChromePage:
    """A headless Chrome with remote debugging, driven over CDP."""

    def __init__(self, port: int, process: subprocess.Popen | None = None):
        self.port = port
        self.process = process
        self.ws: WebSocket | None = None
        self._id = 0
        self._target_id: str | None = None
        self.events: list[dict] = []

    # -- lifecycle ----------------------------------------------------------

    @classmethod
    def launch(
        cls,
        profile_dir: Path,
        port: int = 9333,
        chrome: str | None = None,
        extra_args: list[str] | None = None,
    ) -> "ChromePage":
        binary = chrome or find_chrome()
        if not binary:
            raise CdpError("Chrome not found")
        profile_dir = Path(profile_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            binary,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-breakpad",
            "--disable-crash-reporter",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "about:blank",
        ] + list(extra_args or [])
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = cls(port, process)
        page.wait_for_devtools()
        return page

    def wait_for_devtools(self, timeout: float = 30.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=2) as response:
                    json.load(response)
                return
            except Exception:
                time.sleep(0.3)
        raise CdpError(f"DevTools endpoint did not appear on port {self.port}")

    def close(self) -> None:
        if self.ws:
            self.ws.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

    # -- targets ------------------------------------------------------------

    def _targets(self) -> list[dict]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=5) as response:
            return json.load(response)

    def connect_page(self, url_contains: str | None = None) -> None:
        targets = [t for t in self._targets() if t.get("type") == "page"]
        if url_contains:
            targets = [t for t in targets if url_contains in t.get("url", "")]
        if not targets:
            raise CdpError("No page target available")
        target = targets[0]
        self._target_id = target["id"]
        self.ws = WebSocket(target["webSocketDebuggerUrl"])

    # -- commands -----------------------------------------------------------

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        if self.ws is None:
            raise CdpError("No page connection; call connect_page() first")
        if self.ws._desynchronised:
            raise CdpError(
                "The DevTools connection lost its frame boundary after a timeout; "
                "reconnect with connect_page() before sending more commands"
            )
        self._id += 1
        message_id = self._id
        self.ws.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise CdpError(f"{method} timed out after {timeout:.1f}s")
            # Bound the socket read by the caller's deadline: a stuck page must
            # surface as a timeout for this command, never as a hung process.
            self.ws.sock.settimeout(max(0.5, remaining))
            try:
                payload = json.loads(self.ws.recv_text())
            except CdpError as exc:
                if "Timed out reading" in str(exc):
                    raise CdpError(f"{method} timed out after {timeout:.1f}s") from exc
                raise
            except json.JSONDecodeError as exc:
                # A malformed frame must not escape as a bare json error: the
                # caller only knows how to report CdpError.
                self.ws._desynchronised = True
                raise CdpError(f"{method} got a malformed DevTools frame: {exc}") from exc
            if "id" not in payload:
                self.events.append(payload)
                continue
            if payload.get("id") == message_id:
                if "error" in payload:
                    raise CdpError(f"{method} failed: {payload['error']}")
                return payload.get("result", {})

    def navigate(self, url: str, wait_seconds: float | None = None, timeout: float = 45.0) -> None:
        """Navigate and wait for the load to settle.

        ``wait_seconds`` is a legacy fixed sleep; prefer the default, which
        waits for ``document.readyState === 'complete'`` and returns as soon as
        the page is actually usable.
        """
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url}, timeout=timeout)
        if wait_seconds is not None:
            time.sleep(wait_seconds)
            return
        self.wait_for(
            "document.readyState === 'complete'",
            description=f"page load of {url}",
            timeout=timeout,
        )

    def wait_for(
        self,
        expression: str,
        description: str = "condition",
        timeout: float = 30.0,
        interval: float = 0.2,
    ):
        """Poll a JS expression until it is truthy; raise with the last value."""
        started = time.time()
        deadline = started + timeout
        last = None
        while True:
            try:
                last = self.eval(f"(() => {{ try {{ return !!({expression}); }} catch (e) {{ return false; }} }})()")
            except CdpError:
                last = None
            if last:
                return last
            if time.time() >= deadline:
                raise CdpError(
                    f"Timed out waiting for {description} after {timeout:.1f}s (last value: {last!r})"
                )
            time.sleep(interval)

    def eval(self, expression: str, timeout: float = 30.0):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise CdpError(f"JS error: {result['exceptionDetails'].get('text')}")
        return result.get("result", {}).get("value")

    def insert_text(self, text: str) -> None:
        self.call("Input.insertText", {"text": text})

    def click(self, x: int, y: int) -> None:
        for event_type in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent",
                {"type": event_type, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    def press_key(self, key: str) -> None:
        for event_type in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": event_type, "key": key, "code": key})

    def screenshot(self, path: Path) -> bool:
        result = self.call("Page.captureScreenshot", {"format": "png"}, timeout=60)
        data = result.get("data")
        if not data:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data))
        return True


def find_chrome() -> str | None:
    import shutil

    roots = [
        Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".agent-browser" / "browsers",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application",
    ]
    for root in roots:
        if root and root.exists():
            found = sorted(root.glob("**/chrome.exe"), reverse=True)
            if found:
                return str(found[0])
    for name in ("chrome", "chrome.exe", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None
