from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import socket
import os
from http.cookiejar import CookieJar
import re
from urllib.request import build_opener, HTTPCookieProcessor

import pytest

from hybrid.php_runtime import resolve_php

# Use the same resolver the engine's quality gate uses, so the functional test and
# the syntax check can never disagree about which PHP runtime the project targets.
# The demo fixture has no composer.json, so this resolves to the newest installed
# build; set HYBRID_PHP_BIN to pin a specific runtime.
_RUNTIME = resolve_php(Path(__file__).parents[1] / "demo_php")
PHP = _RUNTIME.path if _RUNTIME else None
pytestmark = pytest.mark.skipif(PHP is None, reason="php executable not found")


@pytest.fixture
def server(tmp_path: Path):
    root = Path(__file__).parents[1] / "demo_php"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [PHP, "-d", "output_buffering=0", "-d", f"session.save_path={tmp_path}", "-S", f"127.0.0.1:{port}", "-t", str(root)],
        cwd=tmp_path,
        env={**os.environ, "HYBRID_DEMO_STATE_DIR": str(tmp_path / "inventory-state")},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/ajax/inventory.php"
    try:
        for _ in range(50):
            try:
                with urlopen(base, timeout=0.2):
                    break
            except Exception:
                if process.poll() is not None:
                    pytest.fail("PHP demo server exited before becoming ready")
                time.sleep(0.05)
        yield base
    finally:
        process.terminate()
        process.wait(timeout=5)


def request(base: str, opener, method: str = "GET", **params: str) -> tuple[int, dict]:
    url = base + ("?" + urlencode(params) if method == "GET" and params else "")
    data = urlencode(params).encode() if method == "POST" else None
    req = Request(url, data=data, method=method, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        response = opener.open(req, timeout=2)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read())


def demo_opener(server: str):
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    page = opener.open(server.replace("/ajax/inventory.php", "/"), timeout=2).read().decode()
    match = re.search(r'name="inventory-csrf" content="([a-f0-9]+)"', page)
    assert match is not None
    return opener, match.group(1)


def test_list_has_owned_quantities_and_filters(server: str) -> None:
    opener, _csrf = demo_opener(server)
    status, payload = request(server, opener, rarity="rare")
    assert status == 200
    assert payload["ok"] is True
    assert [(item["id"], item["quantity"]) for item in payload["items"]] == [(3, 2)]


def test_use_is_post_only_and_idempotent(server: str) -> None:
    opener, csrf = demo_opener(server)
    key = "12345678-1234-4234-8234-123456789abc"
    first_status, first = request(server, opener, "POST", action="use", id="4", request_key=key, csrf=csrf)
    second_status, second = request(server, opener, "POST", action="use", id="4", request_key=key, csrf=csrf)
    assert first_status == second_status == 200
    assert first["replayed"] is False
    assert second["replayed"] is True
    assert not any(item["id"] == 4 for item in second["items"])


def test_use_rejects_non_consumable_missing_item_and_invalid_key(server: str) -> None:
    opener, csrf = demo_opener(server)
    key = "12345678-1234-4234-8234-123456789abc"
    assert request(server, opener, "POST", action="use", id="1", request_key=key, csrf=csrf)[0] == 409
    assert request(server, opener, "POST", action="use", id="99", request_key=key, csrf=csrf)[0] == 404
    assert request(server, opener, "POST", action="use", id="4", request_key="bad", csrf=csrf)[0] == 400
    assert request(server, opener, "GET", action="use", id="4", request_key=key, csrf=csrf)[0] == 400


def test_equip_is_post_only_idempotent_and_reflected_in_inventory(server: str) -> None:
    opener, csrf = demo_opener(server)
    key = "22345678-1234-4234-8234-123456789abc"
    first_status, first = request(server, opener, "POST", action="equip", id="1", request_key=key, csrf=csrf)
    second_status, second = request(server, opener, "POST", action="equip", id="1", request_key=key, csrf=csrf)
    assert first_status == second_status == 200
    assert first["replayed"] is False
    assert second["replayed"] is True
    equipped = {item["id"]: item["equipped"] for item in second["items"]}
    assert equipped[1] is True
    assert equipped[2] is False
    assert request(server, opener)[1]["items"][0]["quantity"] == 1


def test_equip_rejects_consumables_missing_items_and_get(server: str) -> None:
    opener, csrf = demo_opener(server)
    key = "32345678-1234-4234-8234-123456789abc"
    assert request(server, opener, "POST", action="equip", id="4", request_key=key, csrf=csrf)[0] == 409
    assert request(server, opener, "POST", action="equip", id="99", request_key=key, csrf=csrf)[0] == 404
    assert request(server, opener, "GET", action="equip", id="1", request_key=key, csrf=csrf)[0] == 400
