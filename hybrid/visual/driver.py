from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time

DEFAULT_TIMEOUT = 120

# Chrome's own diagnostics, not page errors. Recognised so that the
# "Console Errors" check means JavaScript errors and nothing else.
BROWSER_NOISE_RE = re.compile(
    r"(sandbox\\policy|network_service_instance_impl|gpu_process|"
    r"voice_transcription|device_event_log|disk_cache|crashpad|"
    r"Registration response error|GetHandleVerifier|CreateFile)",
    re.IGNORECASE,
)


@dataclass
class Shot:
    viewport: str
    path: Path
    url: str
    ok: bool
    detail: str = ""


@dataclass
class DriverResult:
    ok: bool
    detail: str
    console: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)


class BrowserDriver(ABC):
    """Opens a local page in a real browser and captures the evidence."""

    name = "browser"

    def available(self) -> tuple[bool, str]:
        return False, "not implemented"

    @abstractmethod
    def capture(
        self,
        url: str,
        viewports: dict[str, tuple[int, int]],
        out_dir: Path,
        session: str,
        log_dir: Path | None = None,
    ) -> DriverResult:
        raise NotImplementedError


class AgentBrowserDriver(BrowserDriver):
    """Drives the `agent-browser` CLI through subprocess.

    Verified against agent-browser 0.38.2:

    - `open <url>` returns immediately once the page is requested (measured
      ~14 ms), so it is safe to call directly;
    - `viewport <w> <h>` resizes the active page;
    - `screenshot <path>` writes the file, but on some Windows hosts it does
      not return even though the page loaded. Every command therefore has a
      hard timeout, and a missing screenshot is reported as a failure rather
      than hanging the whole run;
    - `console` prints captured console output;
    - `network requests --status 4xx-5xx` lists failed requests.
    """

    name = "agent-browser"

    def __init__(
        self,
        command: str = "agent-browser",
        timeout_seconds: int = DEFAULT_TIMEOUT,
        command_timeout_seconds: int = 60,
    ):
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.command_timeout_seconds = command_timeout_seconds

    # -- discovery ----------------------------------------------------------

    def _resolve(self) -> str | None:
        if Path(self.command).is_absolute():
            return self.command if Path(self.command).exists() else None
        return shutil.which(self.command)

    def available(self) -> tuple[bool, str]:
        resolved = self._resolve()
        if not resolved:
            return False, f"{self.command} not found in PATH"
        try:
            proc = self._run(["--version"], timeout=60)
        except Exception as exc:  # pragma: no cover - host specific
            return False, f"agent-browser is not usable: {exc}"
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout).strip()[:200] or "agent-browser --version failed"
        return True, (proc.stdout or proc.stderr).strip()[:120] or "agent-browser"

    # -- capture ------------------------------------------------------------

    def capture(
        self,
        url: str,
        viewports: dict[str, tuple[int, int]],
        out_dir: Path,
        session: str,
        log_dir: Path | None = None,
    ) -> DriverResult:
        ok, detail = self.available()
        if not ok:
            return DriverResult(False, detail)

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        logs = Path(log_dir) if log_dir else out_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        shots: list[Shot] = []
        notes: list[str] = []
        console: list[str] = []
        failed: list[str] = []

        try:
            opened = self._run(
                ["open", url],
                session=session,
                timeout=self.timeout_seconds,
                tolerate_timeout=True,
                log_path=logs / "open.log",
            )
            if opened.returncode != 0:
                return DriverResult(False, (opened.stderr or opened.stdout).strip()[:300] or "open failed")
            if opened.stderr == "__timeout__":
                notes.append("open command exceeded the timeout; the page was still requested and screenshots were attempted")

            for name, (width, height) in viewports.items():
                path = out_dir / f"{name}.png"
                resize = self._run(
                    ["viewport", str(width), str(height)],
                    session=session,
                    timeout=self.command_timeout_seconds,
                    log_path=logs / f"viewport-{name}.log",
                )
                if resize.returncode != 0:
                    shots.append(Shot(name, path, url, False, f"viewport failed: {(resize.stderr or resize.stdout).strip()[:200]}"))
                    continue
                shot = self._run(
                    ["screenshot", str(path)],
                    session=session,
                    timeout=self.command_timeout_seconds,
                    log_path=logs / f"screenshot-{name}.log",
                )
                produced = path.is_file() and path.stat().st_size > 0
                detail = "" if produced else (shot.stderr or shot.stdout).strip()[:200] or "screenshot file was not written"
                shots.append(Shot(name, path, url, produced, detail))

            console = self._console(session, logs)
            failed = self._failed_requests(session, logs)
        finally:
            self._run(["close"], session=session, timeout=60, log_path=logs / "close.log")

        captured = [shot for shot in shots if shot.ok]
        return DriverResult(
            ok=bool(captured),
            detail="; ".join(notes) or f"{len(captured)}/{len(viewports)} viewports captured",
            console=console,
            failed_requests=failed,
            shots=shots,
        )

    # -- internals ----------------------------------------------------------

    def _console(self, session: str, logs: Path | None = None) -> list[str]:
        proc = self._run(["console"], session=session, log_path=(logs / "console.log") if logs else None)
        if proc.returncode != 0:
            return []
        lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
        return [line for line in lines if "error" in line.lower()]

    def _failed_requests(self, session: str, logs: Path | None = None) -> list[str]:
        proc = self._run(
            ["network", "requests", "--status", "400-599"],
            session=session,
            log_path=(logs / "network.log") if logs else None,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]

    def _run(self, args: list[str], session: str | None = None, timeout: int | None = None, tolerate_timeout: bool = False, log_path: Path | None = None):
        """Run one CLI command with a hard deadline.

        Output goes to a log file (or DEVNULL) instead of pipes: the CLI starts
        a detached browser that inherits the pipe, and a killed command would
        otherwise keep the pipe open and hang the parent forever.
        """
        command = [self._resolve() or self.command]
        if session:
            command += ["--session", session]
        command += args
        if log_path is None:
            handle_target = subprocess.DEVNULL
            handle = None
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_path, "w", encoding="utf-8", newline="\n")
            handle_target = handle
        try:
            try:
                proc = subprocess.run(
                    command,
                    text=True,
                    stdout=handle_target,
                    stderr=subprocess.STDOUT,
                    timeout=timeout or self.timeout_seconds,
                    check=False,
                )
                output = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.exists() else ""
                return subprocess.CompletedProcess(command, proc.returncode, stdout=output, stderr="")
            except subprocess.TimeoutExpired:
                if tolerate_timeout:
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="__timeout__")
                return subprocess.CompletedProcess(command, 1, stdout="", stderr=f"{' '.join(args)} timed out")
            except FileNotFoundError as exc:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr=str(exc))
        finally:
            if handle is not None:
                handle.close()


class ChromeScreenshotDriver(BrowserDriver):
    """Headless Chrome screenshot driver (no extra dependencies).

    Works with the browser that `agent-browser install` already downloaded, or
    any Chrome/Edge executable. Measured on this host: ~1 second per viewport,
    which is why it is the default driver. The browser is launched directly in
    batch mode; on Windows the CLI progress output stays on stderr, so stdout
    is clean and no pipe is inherited by a detached process.
    """

    name = "chrome-headless"

    def __init__(self, command: str | None = None, timeout_seconds: int = 60):
        self.command = command or find_chrome()
        self.timeout_seconds = timeout_seconds

    def available(self) -> tuple[bool, str]:
        if not self.command or not Path(self.command).exists():
            return False, "no Chrome/Chromium executable found; set visual.command or run `agent-browser install`"
        return True, self.command

    def capture(self, url, viewports, out_dir, session, log_dir=None) -> DriverResult:
        ok, detail = self.available()
        if not ok:
            return DriverResult(False, detail)

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        logs = Path(log_dir) if log_dir else out_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)

        target = to_file_url(url) if not str(url).lower().startswith(("http://", "https://", "file:", "data:")) else url
        shots: list[Shot] = []
        errors: list[str] = []
        browser_noise: list[str] = []
        for name, (width, height) in viewports.items():
            path = out_dir / f"{name}.png"
            command = [
                self.command,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--mute-audio",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-breakpad",
                "--disable-crash-reporter",
                "--force-device-scale-factor=1",
                f"--window-size={width},{height}",
                f"--screenshot={path}",
                "--virtual-time-budget=5000",
                target,
            ]
            log_path = logs / f"chrome-{name}.log"
            proc = _run_file_logged(command, log_path, timeout=self.timeout_seconds)
            produced = path.is_file() and path.stat().st_size > 0
            output = (proc.stdout or "") + (proc.stderr or "")
            for line in output.splitlines():
                lowered = line.lower()
                if "error" not in lowered or "written to file" in lowered:
                    continue
                # Chrome's own diagnostics are not page errors; keep them
                # separate so "Console Errors" means JavaScript errors only.
                if BROWSER_NOISE_RE.search(line):
                    browser_noise.append(line.strip()[:160])
                else:
                    errors.append(f"{name}: {line.strip()[:200]}")
            shots.append(Shot(name, path, url, produced, "" if produced else output.strip()[:200] or "screenshot file was not written"))
        captured = [shot for shot in shots if shot.ok]
        detail = f"{len(captured)}/{len(viewports)} viewports captured"
        if browser_noise:
            detail += f"; browser diagnostics ignored: {len(browser_noise)}"
        return DriverResult(
            ok=bool(captured),
            detail=detail,
            console=errors[:10],
            failed_requests=[],
            shots=shots,
        )


class CDPChromeScreenshotDriver(ChromeScreenshotDriver):
    """Capture exact CSS viewports and collect page diagnostics through CDP."""

    name = "chrome-cdp"

    def capture(self, url, viewports, out_dir, session, log_dir=None) -> DriverResult:
        ok, detail = self.available()
        if not ok:
            return DriverResult(False, detail)

        from hybrid.browser_bridge.cdp import CdpError, ChromePage

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        shots: list[Shot] = []
        errors: list[str] = []
        failed_requests: list[str] = []
        port = _available_local_port()
        try:
            with tempfile.TemporaryDirectory(prefix="hybrid-visual-") as profile:
                page = ChromePage.launch(
                    Path(profile), port=port, chrome=self.command,
                    extra_args=["--force-device-scale-factor=1"],
                )
                try:
                    page.connect_page()
                    page.call("Runtime.enable")
                    page.call("Log.enable")
                    page.call("Network.enable")
                    for name, (width, height) in viewports.items():
                        path = out_dir / f"{name}.png"
                        page.call(
                            "Emulation.setDeviceMetricsOverride",
                            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width <= 640},
                        )
                        page.navigate(url, timeout=self.timeout_seconds)
                        page.wait_for("document.readyState === 'complete'", description=f"{name} page load", timeout=self.timeout_seconds)
                        # Give immediate scripts and their requests a chance to settle.
                        time.sleep(0.25)
                        captured = page.screenshot(path)
                        shots.append(Shot(name, path, url, captured, "" if captured else "Chrome returned no screenshot data"))
                        viewport_errors, viewport_failures = _page_diagnostics(page.events)
                        errors.extend(f"{name}: {item}" for item in viewport_errors)
                        failed_requests.extend(f"{name}: {item}" for item in viewport_failures)
                        page.events.clear()
                finally:
                    page.close()
        except (CdpError, OSError, TimeoutError, ValueError) as exc:
            if not shots:
                return DriverResult(False, f"Chrome CDP capture failed: {exc}")
            errors.append(f"Chrome CDP capture failed: {exc}")

        captured = [shot for shot in shots if shot.ok]
        return DriverResult(
            ok=bool(captured),
            detail=f"{len(captured)}/{len(viewports)} viewports captured via exact CSS emulation",
            console=errors[:10],
            failed_requests=failed_requests[:10],
            shots=shots,
        )


def _available_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _page_diagnostics(events: list[dict]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    failures: list[str] = []
    request_urls: dict[str, str] = {}
    for event in events:
        method = event.get("method")
        params = event.get("params", {})
        if method == "Network.requestWillBeSent":
            request = params.get("request", {})
            request_urls[str(params.get("requestId", ""))] = str(request.get("url", ""))
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            status = int(response.get("status", 0))
            if status >= 400:
                failures.append(f"HTTP {status} {response.get('url', '')}")
        elif method == "Network.loadingFailed":
            request_id = str(params.get("requestId", ""))
            failures.append(f"{params.get('errorText', 'request failed')} {request_urls.get(request_id, '')}".strip())
        elif method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            exception = details.get("exception", {})
            errors.append(str(exception.get("description") or details.get("text") or "Uncaught browser exception"))
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") == "error":
                errors.append(str(entry.get("text") or "Browser console error"))
    return list(dict.fromkeys(errors)), list(dict.fromkeys(failures))


def _run_file_logged(command: list[str], log_path: Path, timeout: int):
    """Run a command with output in a file and a hard deadline."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", newline="\n") as handle:
        try:
            proc = subprocess.run(
                command,
                text=True,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            output = log_path.read_text(encoding="utf-8", errors="replace")
            return subprocess.CompletedProcess(command, proc.returncode, stdout=output, stderr="")
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr=f"chrome timed out after {timeout}s")
        except FileNotFoundError as exc:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr=str(exc))


def find_chrome() -> str | None:
    """Locate a Chrome/Chromium binary: agent-browser cache first, then PATH."""
    import os

    roots = [
        Path(os.environ.get("USERPROFILE", Path.home())) / ".agent-browser" / "browsers",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application",
    ]
    for root in roots:
        if not root or not root.exists():
            continue
        for candidate in sorted(root.glob("**/chrome.exe"), reverse=True):
            return str(candidate)
    for name in ("chrome", "chrome.exe", "google-chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def to_file_url(url: str) -> str:
    value = str(url)
    if value.lower().startswith("file:"):
        return value
    return Path(value).resolve().as_uri()


class FakeDriver(BrowserDriver):
    """Deterministic driver for tests: writes tiny PNG files, records calls."""

    name = "fake"

    PNG = b"\x89PNG\r\n\x1a\n"

    def __init__(
        self,
        available: bool = True,
        console: list[str] | None = None,
        failed_requests: list[str] | None = None,
        skip_viewports: tuple[str, ...] = (),
        detail: str = "fake driver",
    ):
        self._available = available
        self._console = list(console or [])
        self._failed = list(failed_requests or [])
        self._skip = set(skip_viewports)
        self._detail = detail
        self.calls: list[tuple[str, str, str]] = []

    def available(self) -> tuple[bool, str]:
        return self._available, self._detail

    def capture(self, url, viewports, out_dir, session, log_dir=None) -> DriverResult:
        self.calls.append(("capture", session, url))
        if not self._available:
            return DriverResult(False, self._detail)
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        shots: list[Shot] = []
        for name in viewports:
            if name in self._skip:
                continue
            path = out_dir / f"{name}.png"
            path.write_bytes(self.PNG)
            shots.append(Shot(name, path, url, True))
        return DriverResult(
            ok=bool(shots),
            detail=self._detail,
            console=list(self._console),
            failed_requests=list(self._failed),
            shots=shots,
        )
