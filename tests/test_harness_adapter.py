from __future__ import annotations

import sys
import time
import types

import pytest
import yaml

from hybrid.config import load_settings
from hybrid.integrations.codex_cli_delegate import CodexCliDelegate
from hybrid.integrations.deepseek_harness import DeepSeekHarnessAdapter


def make_codex_capture_stub(directory, capture, body):
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / "codex_stub.py"
    script.write_text(body, encoding="utf-8", newline="\n")
    if sys.platform == "win32":
        target = directory / "codex.cmd"
        target.write_text(
            f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n',
            encoding="utf-8",
            newline="\r\n",
        )
    else:
        target = directory / "codex"
        target.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n", encoding="utf-8", newline="\n")
        target.chmod(0o755)
    return target


def test_disabled_harness_is_unavailable_and_run_does_not_import(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "deepseek_harness_sdk", raising=False)
    adapter = DeepSeekHarnessAdapter({"enabled": False, "max_parallel_agents": 2, "timeout_seconds": 180})

    assert adapter.available() == (False, "disabled by configuration")
    result = adapter.run_task("do work", tmp_path)

    assert result.status == "unavailable"
    assert result.error == "disabled by configuration"


def test_missing_sdk_reports_clear_error(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "deepseek_harness_sdk", raising=False)
    adapter = DeepSeekHarnessAdapter({"enabled": True, "max_parallel_agents": 2, "timeout_seconds": 180})

    ok, detail = adapter.available()
    result = adapter.run_task("do work", tmp_path)

    assert ok is False
    assert detail == "deepseek-harness-sdk is not installed"
    assert result.status == "unavailable"
    assert result.error == "deepseek-harness-sdk is not installed"


def test_fake_sdk_run_returns_ok(tmp_path, monkeypatch):
    module = types.ModuleType("deepseek_harness_sdk")
    module.__version__ = "0.1-test"
    module.run = lambda description, cwd, env: f"{description} in {cwd.name}"
    monkeypatch.setitem(sys.modules, "deepseek_harness_sdk", module)
    adapter = DeepSeekHarnessAdapter({"enabled": True, "max_parallel_agents": 2, "timeout_seconds": 180})

    assert adapter.available() == (True, "deepseek_harness_sdk 0.1-test")
    result = adapter.run_task("do work", tmp_path)

    assert result.status == "ok", result.error
    assert result.output == f"do work in {tmp_path.name}"


def test_fake_sdk_timeout_returns_error_without_waiting(tmp_path, monkeypatch):
    module = types.ModuleType("deepseek_harness_sdk")

    def slow_run(description, cwd, env):
        time.sleep(0.2)
        return "too late"

    module.run = slow_run
    monkeypatch.setitem(sys.modules, "deepseek_harness_sdk", module)
    adapter = DeepSeekHarnessAdapter({"enabled": True, "max_parallel_agents": 2, "timeout_seconds": 1})

    result = adapter.run_task("do work", tmp_path, timeout=0)

    assert result.status == "error"
    assert result.error == "deepseek harness timed out after 0s"


def test_inside_agent_blocks_recursive_run(tmp_path, monkeypatch):
    module = types.ModuleType("deepseek_harness_sdk")
    module.run = lambda description, cwd, env: pytest.fail("SDK should not run recursively")
    monkeypatch.setitem(sys.modules, "deepseek_harness_sdk", module)
    monkeypatch.setenv("HYBRID_INSIDE_AGENT", "1")
    adapter = DeepSeekHarnessAdapter({"enabled": True, "max_parallel_agents": 2, "timeout_seconds": 180})

    result = adapter.run_task("do work", tmp_path)

    assert result.status == "error"
    assert result.error == "recursive harness execution is disabled"


def test_provider_api_keys_are_not_passed_to_sdk_env(tmp_path, monkeypatch):
    captured = {}
    module = types.ModuleType("deepseek_harness_sdk")

    def fake_run(description, cwd, env):
        captured.update(env)
        return "ok"

    module.run = fake_run
    monkeypatch.setitem(sys.modules, "deepseek_harness_sdk", module)
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-secret")
    adapter = DeepSeekHarnessAdapter({"enabled": True, "max_parallel_agents": 2, "timeout_seconds": 180})

    result = adapter.run_task("do work", tmp_path)

    assert result.status == "ok"
    assert "GROQ_API_KEY" not in captured
    assert "OPENROUTER_API_KEY" not in captured


def test_invalid_max_parallel_agents_type_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "missing-user-settings.yaml"))
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"deepseek_harness": {"max_parallel_agents": "two"}}),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ValueError, match="deepseek_harness.max_parallel_agents must be a positive integer"):
        load_settings(tmp_path)


def test_harness_doctor_reports_disabled_configuration(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "missing-user-settings.yaml"))
    from hybrid.cli import main

    code = main(["--project", str(tmp_path), "harness", "doctor"])
    output = capsys.readouterr().out

    assert code == 1
    assert "DeepSeek Harness SDK: UNAVAILABLE" in output
    assert "Enabled: False" in output


def test_codex_cli_delegate_runs_with_safe_default_sandbox(tmp_path, monkeypatch):
    capture = tmp_path / "capture.json"
    stub = make_codex_capture_stub(
        tmp_path,
        capture,
        (
            "import json, os, sys\n"
            "prompt = sys.stdin.read()\n"
            "out = sys.argv[sys.argv.index('-o') + 1]\n"
            "open(out, 'w', encoding='utf-8').write('delegated ok')\n"
            "payload = {'argv': sys.argv[1:], 'prompt': prompt, "
            "'secrets': [k for k in os.environ if k.endswith('_API_KEY')]}\n"
            f"open(r'{capture}', 'w', encoding='utf-8').write(json.dumps(payload))\n"
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    delegate = CodexCliDelegate({"command": str(stub), "timeout_seconds": 15})

    result = delegate.run_task("review the browser bridge", tmp_path, output_path=tmp_path / "answer.md")

    captured = yaml.safe_load(capture.read_text(encoding="utf-8"))
    assert result.status == "ok"
    assert result.output == "delegated ok"
    assert captured["argv"][:2] == ["exec", "-C"]
    assert "--sandbox" in captured["argv"]
    assert captured["argv"][captured["argv"].index("--sandbox") + 1] == "read-only"
    assert "--dangerously-bypass-approvals-and-sandbox" not in captured["argv"]
    assert captured["secrets"] == []
    assert captured["argv"][-1] == "-"
    assert "DeepSeek Harness" in captured["prompt"]
    assert "review the browser bridge" in captured["prompt"]


def test_harness_codex_cli_reads_task_file_and_prints_json(tmp_path, capsys, monkeypatch):
    capture = tmp_path / "capture.json"
    stub = make_codex_capture_stub(
        tmp_path,
        capture,
        (
            "import json, sys\n"
            "if sys.argv[1] == 'sandbox':\n"
            "    raise SystemExit(0)\n"
            "out = sys.argv[sys.argv.index('-o') + 1]\n"
            "open(out, 'w', encoding='utf-8').write('done')\n"
            f"open(r'{capture}', 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
        ),
    )
    trusted = tmp_path / "trusted.yaml"
    trusted.write_text(
        yaml.safe_dump({"providers": {"codex": {"command": str(stub), "timeout_seconds": 15}}}),
        encoding="utf-8",
        newline="\n",
    )
    task_file = tmp_path / "task.md"
    output_file = tmp_path / "codex-answer.md"
    task_file.write_text("make a read-only audit", encoding="utf-8", newline="\n")
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(trusted))
    from hybrid.cli import main

    code = main(
        [
            "--project",
            str(tmp_path),
            "harness",
            "codex",
            "--file",
            str(task_file),
            "--output",
            str(output_file),
            "--sandbox",
            "workspace-write",
            "--json",
        ]
    )
    payload = yaml.safe_load(capsys.readouterr().out)
    captured = yaml.safe_load(capture.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["status"] == "ok"
    assert payload["output_path"] == str(output_file.resolve())
    assert "workspace-write" in payload["command"]
    assert output_file.read_text(encoding="utf-8").startswith("done")


def test_codex_cli_delegate_fails_fast_when_workspace_sandbox_is_broken(tmp_path):
    capture = tmp_path / "capture.json"
    stub = make_codex_capture_stub(
        tmp_path,
        capture,
        (
            "import json, sys\n"
            "open('capture.json', 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
            "if len(sys.argv) > 1 and sys.argv[1] == 'sandbox':\n"
            "    print('windows sandbox failed helper_unknown_error')\n"
            "    raise SystemExit(1)\n"
            "raise SystemExit('codex exec should not run')\n"
        ),
    )
    delegate = CodexCliDelegate({"command": str(stub), "timeout_seconds": 15})

    result = delegate.run_task("edit files", tmp_path, sandbox="workspace-write", output_path=tmp_path / "answer.md")

    captured = yaml.safe_load(capture.read_text(encoding="utf-8"))
    assert result.status == "error"
    assert captured[:2] == ["sandbox", "windows"]
    assert "sandbox preflight failed" in result.error
    assert not (tmp_path / "answer.md").exists()


def test_codex_cli_delegate_stops_on_unclassified_doctor_failure(tmp_path):
    capture = tmp_path / "capture.json"
    stub = make_codex_capture_stub(
        tmp_path,
        capture,
        (
            "import json, sys\n"
            f"open(r'{capture}', 'w', encoding='utf-8').write(json.dumps(sys.argv[1:]))\n"
            "if sys.argv[1] == 'sandbox':\n"
            "    raise SystemExit('preflight failed for an unknown reason')\n"
            "raise SystemExit('exec must not run')\n"
        ),
    )
    result = CodexCliDelegate({"command": str(stub)}).run_task(
        "edit", tmp_path, sandbox="workspace-write"
    )

    assert result.status == "error"
    assert yaml.safe_load((tmp_path / "capture.json").read_text(encoding="utf-8"))[:2] == ["sandbox", "windows"]
    assert "sandbox preflight failed" in result.error


def test_codex_cli_delegate_workspace_write_uses_temporary_copy(tmp_path):
    capture = tmp_path / "capture.json"
    stub = make_codex_capture_stub(
        tmp_path,
        capture,
        (
            "import json, os, sys\n"
            "if sys.argv[1] == 'sandbox':\n"
            "    raise SystemExit(0)\n"
            "payload = {'cwd': os.getcwd(), 'project': sys.argv[sys.argv.index('-C') + 1]}\n"
            "open('capture.json', 'w', encoding='utf-8').write(json.dumps(payload))\n"
            "open('changed.txt', 'w', encoding='utf-8').write('changed')\n"
            "out = sys.argv[sys.argv.index('-o') + 1]\n"
            "open(out, 'w', encoding='utf-8').write('edited')\n"
        ),
    )
    (tmp_path / "source.txt").write_text("original", encoding="utf-8")

    result = CodexCliDelegate({"command": str(stub)}).run_task(
        "edit", tmp_path, sandbox="workspace-write"
    )

    assert result.status == "ok", result.error
    assert "hybrid-codex-" in result.command[3]
    assert result.command[3] == result.command[result.command.index("-C") + 1]
    saved_output = (tmp_path / ".hybrid" / "harness" / "codex-result.md").read_text(encoding="utf-8")
    assert saved_output.startswith("edited")
    assert "--- WORKSPACE PATCH ---" in saved_output
    assert (tmp_path / "source.txt").read_text(encoding="utf-8") == "original"


def test_codex_delegate_safe_env_does_not_inherit_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "attacker-controlled-codex-home"))
    delegate = CodexCliDelegate({"command": "codex"})

    env = delegate.provider._safe_env(str(tmp_path / "codex.exe"))

    assert "CODEX_HOME" not in env
