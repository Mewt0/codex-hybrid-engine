"""Smoke test for the local Web Workspace (real HTTP, localhost only).

    python tools/smoke_local_ui.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge import BrowserBridge
from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.local_ui import LocalUI


def fetch(url: str, data: dict | None = None, headers: dict | None = None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def main() -> int:
    project_dir = ROOT / "demo_project"
    if not (project_dir / ".git").exists():
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=project_dir, check=False)
        subprocess.run(["git", "config", "user.email", "demo@example.invalid"], cwd=project_dir, check=False)
        subprocess.run(["git", "config", "user.name", "Demo"], cwd=project_dir, check=False)
        subprocess.run(["git", "add", "-A"], cwd=project_dir, check=False)
        subprocess.run(["git", "commit", "-qm", "demo baseline"], cwd=project_dir, check=False)

    settings = load_settings(project_dir)
    controller = Controller(settings)
    bridge = BrowserBridge(settings, controller)
    ui = LocalUI(settings, bridge, controller, port=0)
    url = ui.start(block=False)
    print(f"server: {url}")
    failures = 0
    try:
        status, body = fetch(url + "health")
        print(f"GET /health -> {status} {body.strip()}")
        failures += status != 200

        status, body = fetch(url + "api/tasks")
        print(f"GET /api/tasks -> {status} {body[:80].strip()}")
        failures += status != 200

        status, body = fetch(url)
        print(f"GET / -> {status}, dashboard links: {'/new' in body}")
        failures += status != 200 or "/new" not in body

        status, body = fetch(url + "new")
        print(f"GET /new -> {status}, has prepare form: {'/prepare' in body}")
        failures += status != 200 or "/prepare" not in body

        status, _ = fetch(url + "prepare", data={"description": "x", "provider": "deepseek_web"})
        print(f"POST /prepare without CSRF -> {status} (expected 403)")
        failures += status != 403

        status, _ = fetch(url + "task/BTASK-NOPE")
        print(f"GET /task/BTASK-NOPE -> {status} (expected 404)")
        failures += status != 404

        status, body = fetch(url + "review/BTASK-NOPE")
        print(f"GET /review/BTASK-NOPE -> {status}")
    finally:
        ui.stop()

    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
