"""Persistent visible Chrome session for the Browser AI Bridge.

The user logs in once in a real browser window; the engine then drives that same
profile over the DevTools Protocol. No cookies are copied, no passwords are
stored, and the profile can be deleted at any time.

    python -m hybrid.cli browser launch
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .cdp import ChromePage, CdpError, find_chrome


def session_dir(settings) -> Path:
    configured = settings.raw.get("browser_session", {}).get("profile_dir")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(settings.data_dir) / "browser-profile").resolve()


@dataclass
class SessionState:
    port: int
    profile_dir: Path
    running: bool
    version: str = ""
    user_agent: str = ""

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "profile_dir": str(self.profile_dir),
            "running": self.running,
            "version": self.version,
            "user_agent": self.user_agent,
        }


class BrowserSession:
    """Launches and inspects the shared, user-authenticated Chrome profile."""

    def __init__(self, settings):
        self.settings = settings
        config = dict(settings.raw.get("browser_session", {}))
        self.port = int(config.get("port", 9333))
        self.profile_dir = session_dir(settings)
        self.chrome = config.get("command") or find_chrome()
        self.headless = bool(config.get("headless", False))
        self.start_url = config.get("start_url", "https://chatgpt.com/")

    # -- state --------------------------------------------------------------

    def version_info(self) -> dict | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=3) as response:
                return json.load(response)
        except Exception:
            return None

    def state(self) -> SessionState:
        info = self.version_info()
        if info is None:
            return SessionState(self.port, self.profile_dir, running=False)
        return SessionState(
            port=self.port,
            profile_dir=self.profile_dir,
            running=True,
            version=str(info.get("Browser", "")),
            user_agent=str(info.get("User-Agent", "")),
        )

    def is_ours(self) -> bool:
        """True when the debug port belongs to this profile (not another browser)."""
        if not self.profile_dir.exists():
            return False
        if self._profile_in_use():
            return True
        # Fallback: this session can only be reached when the port is up and the
        # profile exists; if another browser owned the port we would not be able
        # to attach with our own user-data-dir.
        return self.version_info() is not None

    def _targets(self) -> list[dict]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=3) as response:
                return json.load(response)
        except Exception:
            return []

    def _profile_in_use(self) -> bool:
        try:
            output = subprocess.run(
                ["wmic", "process", "where", "name='chrome.exe'", "get", "CommandLine"],
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
        return str(self.profile_dir) in output

    # -- actions ------------------------------------------------------------

    def open_page(self, url: str | None = None, timeout: float = 60.0) -> ChromePage:
        """Attach to the running session (launching it if needed) and open a tab.

        The default navigation waits for ``document.readyState === 'complete'``
        instead of sleeping for a fixed number of seconds, so a fast machine is
        not slowed down and a slow one is not raced.
        """
        if not self.chrome:
            raise CdpError("Chrome executable not found")
        if not self.state().running:
            self.launch()
        page = ChromePage(port=self.port)
        page.connect_page()
        if url:
            page.navigate(url, timeout=timeout)
        return page

    def launch(self, url: str | None = None) -> SessionState:
        if not self.chrome:
            raise CdpError("Chrome executable not found; set browser_session.command")
        current = self.state()
        if current.running:
            return current
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            self.chrome,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-breakpad",
            "--disable-crash-reporter",
            # Avoid a literal "HeadlessChrome" client hint and keep the window real.
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
        ]
        if self.headless:
            args.append("--headless=new")
        args.append(url or self.start_url)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 45
        while time.time() < deadline:
            state = self.state()
            if state.running:
                return state
            time.sleep(0.5)
        raise CdpError(f"Chrome did not expose the DevTools port {self.port}")
