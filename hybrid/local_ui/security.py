from __future__ import annotations

from http.client import HTTPMessage
from secrets import token_urlsafe
from urllib.parse import urlparse


MAX_POST_BYTES = 1024 * 1024


def csrf_token() -> str:
    return token_urlsafe(32)


def check_csrf(form: dict[str, list[str]], expected: str) -> bool:
    values = form.get("csrf", [])
    return bool(values and values[0] and values[0] == expected)


def same_origin_ok(headers: HTTPMessage, host: str, port: int) -> bool:
    expected_host = f"{host}:{port}"
    request_host = (headers.get("Host") or "").strip().lower()
    if request_host != expected_host.lower():
        return False
    origin = headers.get("Origin")
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.scheme == "http" and parsed.netloc.lower() == expected_host.lower()


def safe_task_id(value: str) -> bool:
    if not value:
        return False
    return all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in value)
