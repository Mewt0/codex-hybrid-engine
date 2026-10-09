from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
import http.client
import json

import pytest
import yaml

from hybrid.browser_bridge import BrowserBridge
from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.local_ui import LocalUI
from test_engine import project, run


ANSWER = """## SUMMARY
Fixed the label text.

## PATCH
```diff
diff --git a/app.js b/app.js
--- a/app.js
+++ b/app.js
@@ -1 +1 @@
-export const value = "BROKEN";
+export const value = "READY";
```

## LIMITATIONS
- browser not run
"""


@pytest.fixture()
def ui(project: Path, tmp_path: Path, monkeypatch):
    trusted = tmp_path / "trusted.yaml"
    trusted.write_text(yaml.safe_dump({"context": {"allowed_files": ["app.js", "index.php"]}}), encoding="utf-8")
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(trusted))
    (project / "index.php").write_text("<?php echo 'hi';\n", encoding="utf-8")
    assert run(["git", "add", "-A"], project).returncode == 0
    assert run(["git", "commit", "-m", "fixture"], project).returncode == 0
    settings = load_settings(project)
    controller = Controller(settings)
    bridge = BrowserBridge(settings, controller)
    local = LocalUI(settings, bridge, controller, port=0)
    local.start(block=False)
    try:
        yield local, bridge, controller, project
    finally:
        local.stop()


def test_rejects_non_loopback_host(project):
    settings = load_settings(project)
    controller = Controller(settings)
    with pytest.raises(ValueError):
        LocalUI(settings, BrowserBridge(settings, controller), controller, host="0.0.0.0")


def test_start_returns_url_and_health_responds(ui):
    local, _, _, _ = ui
    assert local.url().startswith("http://127.0.0.1:")
    payload = json.loads(get(local.url() + "health"))
    assert payload["status"] == "ok"


def test_dashboard_contains_prepared_task(ui):
    local, bridge, _, _ = ui
    task = bridge.prepare("fix label", "deepseek_web", "frontend")
    assert task.task_id in get(local.url())


def test_prepare_post_creates_task_and_redirects(ui):
    local, bridge, _, _ = ui
    status, headers, _ = post(local, "/prepare", {"description": "fix label", "provider": "deepseek_web", "profile": "frontend"})
    assert status == 303
    assert headers["Location"].startswith("/task/BTASK-")
    assert len(bridge.history()) == 1


def test_post_without_csrf_is_forbidden(ui):
    local, _, _, _ = ui
    with pytest.raises(HTTPError) as exc:
        raw_post(local.url() + "prepare", {"description": "x"})
    assert exc.value.code == 403


def test_post_with_foreign_origin_is_forbidden(ui):
    local, _, _, _ = ui
    with pytest.raises(HTTPError) as exc:
        raw_post(local.url() + "prepare", {"csrf": local.server.csrf_token}, origin="http://example.com")
    assert exc.value.code == 403


def test_unknown_task_is_404(ui):
    local, _, _, _ = ui
    with pytest.raises(HTTPError) as exc:
        get(local.url() + "task/BTASK-MISSING")
    assert exc.value.code == 404


def test_import_valid_patch_sets_ready_and_diff(ui):
    local, bridge, _, _ = ui
    task = bridge.prepare("fix label", "deepseek_web", "frontend")
    status, _, _ = post(local, "/import", {"task_id": task.task_id, "text": ANSWER})
    assert status == 303
    assert bridge.review_payload(task.task_id)["status"] == "ready_for_review"
    assert "READY" in get(local.url() + f"diff/{task.task_id}")


def test_repeat_import_returns_409(ui):
    local, bridge, _, _ = ui
    task = bridge.prepare("fix label", "deepseek_web", "frontend")
    post(local, "/import", {"task_id": task.task_id, "text": ANSWER})
    with pytest.raises(HTTPError) as exc:
        post(local, "/import", {"task_id": task.task_id, "text": ANSWER})
    assert exc.value.code == 409


def test_apply_without_confirm_does_not_change_project(ui):
    local, bridge, _, project = ui
    task = bridge.prepare("fix label", "deepseek_web", "frontend")
    post(local, "/import", {"task_id": task.task_id, "text": ANSWER})
    with pytest.raises(HTTPError) as exc:
        post(local, "/apply", {"task_id": task.task_id, "confirm": "NO"})
    assert exc.value.code == 409
    assert '"BROKEN"' in (project / "app.js").read_text(encoding="utf-8")


def test_apply_with_confirm_changes_project(ui):
    local, bridge, _, project = ui
    task = bridge.prepare("fix label", "deepseek_web", "frontend")
    post(local, "/import", {"task_id": task.task_id, "text": ANSWER})
    status, _, _ = post(local, "/apply", {"task_id": task.task_id, "confirm": "APPLY"})
    assert status == 303
    assert '"READY"' in (project / "app.js").read_text(encoding="utf-8")


def test_html_escapes_task_description(ui):
    local, bridge, _, _ = ui
    task = bridge.prepare("<script>alert(1)</script>", "deepseek_web", "frontend")
    html = get(local.url() + f"task/{task.task_id}")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_large_post_body_returns_413(ui):
    local, _, _, _ = ui
    conn = http.client.HTTPConnection("127.0.0.1", local.server.server_address[1], timeout=5)
    try:
        conn.putrequest("POST", "/prepare")
        conn.putheader("Host", f"127.0.0.1:{local.server.server_address[1]}")
        conn.putheader("Content-Type", "application/x-www-form-urlencoded")
        conn.putheader("Content-Length", str(1024 * 1024 + 1))
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 413
    finally:
        conn.close()


def get(url: str) -> str:
    with build_opener().open(url, timeout=5) as response:
        return response.read().decode("utf-8")


def post(local: LocalUI, path: str, data: dict[str, str]):
    body = dict(data)
    body.setdefault("csrf", local.server.csrf_token)
    return raw_post(local.url() + path.lstrip("/"), body, origin=local.url().rstrip("/"))


def raw_post(url: str, data: dict[str, str], origin: str | None = None):
    encoded = urlencode(data).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if origin:
        headers["Origin"] = origin
    request = Request(url, data=encoded, headers=headers, method="POST")
    opener = build_opener(NoRedirect)
    with opener.open(request, timeout=5) as response:
        return response.status, response.headers, response.read().decode("utf-8")


class NoRedirect(HTTPRedirectHandler):
    def http_error_303(self, req, fp, code, msg, headers):
        return fp
