from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from json import dumps
from traceback import format_exception_only
from urllib.parse import parse_qs, urlparse

from hybrid.browser_bridge import BrowserBridgeError, ResponseAlreadyImported

from . import renderer
from .security import MAX_POST_BYTES, check_csrf, same_origin_ok, safe_task_id


class LocalUIHandler(BaseHTTPRequestHandler):
    server_version = "HybridLocalUI/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        try:
            self._route_get(urlparse(self.path).path)
        except (BrowserBridgeError, KeyError) as exc:
            self._send_html(404, renderer.error_page(404, str(exc)))
        except Exception as exc:
            self._send_html(500, renderer.error_page(500, _safe_error(exc)))

    def do_POST(self) -> None:
        try:
            if not same_origin_ok(self.headers, self.server.ui_host, self.server.ui_port):
                self._send_text(403, "Forbidden")
                return
            form = self._read_form()
            if form is None:
                return
            if not check_csrf(form, self.server.csrf_token):
                self._send_text(403, "Forbidden")
                return
            self._route_post(urlparse(self.path).path, form)
        except (BrowserBridgeError, ResponseAlreadyImported) as exc:
            self._send_text(409, str(exc))
        except KeyError as exc:
            self._send_text(404, str(exc))
        except Exception as exc:
            self._send_text(409, _safe_error(exc))

    def _route_get(self, path: str) -> None:
        if path == "/":
            self._send_html(200, renderer.dashboard(self.server.bridge.history()))
            return
        if path == "/new":
            self._send_html(200, renderer.new_task(self.server.csrf_token, self.server.bridge.provider_names()))
            return
        if path == "/health":
            self._send_json(200, {"status": "ok", "tasks": len(self.server.bridge.history())})
            return
        if path == "/api/tasks":
            self._send_json(200, [task.to_dict() for task in self.server.bridge.history()])
            return
        prefix_routes = {
            "/task/": self._get_task,
            "/diff/": self._get_diff,
            "/review/": self._get_review,
            "/open/": self._get_open,
        }
        for prefix, handler in prefix_routes.items():
            if path.startswith(prefix):
                task_id = path[len(prefix):]
                if not safe_task_id(task_id):
                    self._send_html(404, renderer.error_page(404, "Unknown task"))
                    return
                handler(task_id)
                return
        self._send_html(404, renderer.error_page(404, "Not found"))

    def _route_post(self, path: str, form: dict[str, list[str]]) -> None:
        if path == "/prepare":
            task = self.server.bridge.prepare(_one(form, "description"), _one(form, "provider"), _one(form, "profile") or None)
            self._redirect(f"/task/{task.task_id}")
            return
        if path == "/import":
            task_id = _one(form, "task_id")
            record = self.server.bridge.import_response(task_id, _one(form, "text"), bool(form.get("force")))
            self._redirect(f"/task/{self._browser_task_id_for_record(task_id, record.task_id)}")
            return
        if path == "/apply":
            task_id = _one(form, "task_id")
            if _one(form, "confirm") != "APPLY":
                self._send_text(409, "Type APPLY to confirm")
                return
            task = self.server.bridge.task(task_id)
            self.server.controller.apply(task.engine_task_id, confirm=True)
            self._redirect(f"/task/{task_id}")
            return
        self._send_text(404, "Not found")

    def _get_task(self, task_id: str) -> None:
        task = self.server.bridge.task(task_id)
        record = self.server.controller.store.get(task.engine_task_id)
        prompt = self.server.bridge.prompt(task_id)
        self._send_html(200, renderer.task_detail(task, record, prompt, self.server.csrf_token))

    def _get_diff(self, task_id: str) -> None:
        self._send_text(200, self.server.bridge.diff(task_id), content_type="text/plain; charset=utf-8")

    def _get_review(self, task_id: str) -> None:
        self._send_json(200, self.server.bridge.review_payload(task_id))

    def _get_open(self, task_id: str) -> None:
        url = self.server.bridge.open(task_id)
        self._send_html(200, renderer.opened(task_id, url))

    def _browser_task_id_for_record(self, fallback: str, engine_task_id: str) -> str:
        for task in self.server.bridge.history():
            if task.engine_task_id == engine_task_id:
                return task.task_id
        return fallback

    def _read_form(self) -> dict[str, list[str]] | None:
        length_header = self.headers.get("Content-Length")
        try:
            length = int(length_header or "0")
        except ValueError:
            self._send_text(400, "Bad Content-Length")
            return None
        if length > MAX_POST_BYTES:
            self._send_text(413, "POST body too large")
            return None
        data = self.rfile.read(length).decode("utf-8", errors="replace")
        return parse_qs(data, keep_blank_values=True)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_html(self, status: int, text: str) -> None:
        self._send_bytes(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def _send_json(self, status: int, payload: object) -> None:
        text = dumps(payload, ensure_ascii=False, indent=2) + "\n"
        self._send_bytes(status, text.encode("utf-8"), "application/json; charset=utf-8")

    def _send_text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        self._send_bytes(status, text.encode("utf-8"), content_type)

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _one(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name, [])
    return values[0] if values else ""


def _safe_error(exc: Exception) -> str:
    return "".join(format_exception_only(type(exc), exc)).strip()
