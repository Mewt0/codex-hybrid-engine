"""Real browser smoke test for the Visual QA driver (Windows).

Starts a tiny local HTTP server, opens it with agent-browser and captures
screenshots. Prints exactly what worked and what did not.

    python tools/smoke_visual_qa.py
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.config import load_settings
from hybrid.visual import VIEWPORTS, AgentBrowserDriver, VisualQA

FIXTURE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hybrid Visual QA fixture</title>
<style>
  :root { --bg:#0e1116; --surface:#161b23; --accent:#d8a13a; --text:#e8e3d9; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui, sans-serif; }
  header { padding:16px; border-bottom:1px solid #2b3441; display:flex; gap:12px; align-items:center; }
  main { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:16px; padding:16px; }
  .card { background:var(--surface); border:1px solid #2b3441; border-radius:12px; padding:16px; }
  button { min-height:44px; min-width:44px; background:var(--accent); border:0; border-radius:8px; font-weight:600; }
  @media (max-width:640px) { main { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header><strong>Инвентарь</strong><span id="state">готово</span></header>
<main id="grid"></main>
<script>
  const grid = document.getElementById('grid');
  for (let i = 1; i <= 6; i += 1) {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = '<h3>Предмет ' + i + '</h3><p>Редкость: обычная</p>';
    const button = document.createElement('button');
    button.textContent = 'Использовать';
    button.addEventListener('click', () => { document.getElementById('state').textContent = 'использован ' + i; });
    card.appendChild(button);
    grid.appendChild(card);
  }
</script>
</body>
</html>
"""


def serve(directory: Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, port


def main() -> int:
    site = ROOT / ".visual-fixture"
    site.mkdir(exist_ok=True)
    (site / "index.html").write_text(FIXTURE, encoding="utf-8", newline="\n")

    httpd, port = serve(site)
    url = f"http://127.0.0.1:{port}/index.html"
    print(f"serving {site} at {url}")

    settings = load_settings(ROOT)
    qa = VisualQA(settings)
    ok, detail = qa.driver.available()
    print(f"driver: {qa.driver.name} available={ok} ({detail})")
    if not ok:
        httpd.shutdown()
        return 1

    try:
        report = qa.run("TASK-VISUAL-SMOKE", url, {"desktop": VIEWPORTS["desktop"], "mobile": VIEWPORTS["mobile"]})
    finally:
        httpd.shutdown()

    print(f"status: {report.status}")
    for check in report.checks:
        print(f"- {check.name}: {check.status} {check.detail}")
    for shot in report.shots:
        size = shot.path.stat().st_size if shot.path.exists() else 0
        print(f"- {shot.viewport}: {shot.path} ({size} bytes)")
    print(f"report: {report.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
