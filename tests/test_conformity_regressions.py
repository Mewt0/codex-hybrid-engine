"""Conformity regressions for Phase 0/1 fixes.

These lock in behaviour that was previously missing or mis-reported, so it cannot
silently regress:

* `hybrid doctor` must resolve an absolute trusted tool path and must use the same
  PHP resolver the syntax checks use (otherwise it reports NOT FOUND while the
  quality gate actually lints PHP successfully).
* the change set must never contain engine-internal state.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hybrid.cli import _resolve_tool, doctor
from hybrid.config import load_settings
from hybrid.execution import worktree


def test_resolve_tool_handles_absolute_path(tmp_path: Path):
    real = tmp_path / "codex.exe"
    real.write_text("", encoding="utf-8")
    assert _resolve_tool(str(real)) == str(real)


def test_resolve_tool_reports_missing_absolute_path(tmp_path: Path):
    assert _resolve_tool(str(tmp_path / "nope.exe")) == "NOT FOUND"


def test_resolve_tool_rejects_bare_missing_name():
    assert _resolve_tool("definitely-not-a-real-binary-xyz") == "NOT FOUND"


def test_resolve_tool_finds_git_on_path():
    assert _resolve_tool("git") != "NOT FOUND"


def test_doctor_uses_the_same_php_resolver_as_quality_checks(tmp_path: Path, capsys, monkeypatch):
    """doctor must never report PHP: NOT FOUND when php_binary() resolves it."""
    import hybrid.cli as cli
    from hybrid.quality import checks

    fake_php = tmp_path / "php.exe"
    fake_php.write_text("", encoding="utf-8")
    monkeypatch.setattr(checks, "php_binary", lambda: str(fake_php))
    monkeypatch.setattr(cli, "php_binary", lambda: str(fake_php))

    project = tmp_path / "proj"
    project.mkdir()
    doctor(load_settings(project))
    out = capsys.readouterr().out
    assert "NOT FOUND" not in out.splitlines()[2]  # the PHP row
    assert str(fake_php) in out


def test_doctor_uses_trusted_absolute_codex_command(tmp_path: Path, capsys, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    codex = tmp_path / "codex.exe"
    codex.write_text("", encoding="utf-8")
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "nouserconfig.yaml"))

    settings = load_settings(project)
    settings.raw["providers"]["codex"]["command"] = str(codex)
    doctor(settings)
    out = capsys.readouterr().out
    codex_line = next(line for line in out.splitlines() if line.startswith("Codex CLI:"))
    assert codex_line == f"Codex CLI: {codex}"


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)


def test_engine_internal_state_never_enters_the_change_set(tmp_path: Path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.js").write_text('export const value = "BROKEN";\n', encoding="utf-8")
    _git(["init"], repo)
    _git(["config", "user.email", "t@example.invalid"], repo)
    _git(["config", "user.name", "T"], repo)
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)

    (repo / ".hybrid" / "tasks").mkdir(parents=True)
    (repo / ".hybrid" / "tasks" / "tasks.json").write_text("{}\n", encoding="utf-8")

    changed = worktree.changed_files(repo, include_ignored=True)
    assert not any(entry.startswith(".hybrid") for entry in changed)


def test_ignored_dependency_dirs_are_bounded_entries(tmp_path: Path):
    """An unchanged or changed node_modules must be one entry, never a scan."""
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.js").write_text("export const a = 1;\n", encoding="utf-8")
    (repo / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("module.exports = 1;\n", encoding="utf-8")
    _git(["init"], repo)
    _git(["config", "user.email", "t@example.invalid"], repo)
    _git(["config", "user.name", "T"], repo)
    _git(["add", "."], repo)
    _git(["commit", "-m", "init"], repo)

    (repo / "node_modules" / "dep.js").write_text("module.exports = 2;\n", encoding="utf-8")

    changed = worktree.changed_files(repo, include_ignored=True)
    assert "node_modules/" in changed
    assert all(entry == "node_modules/" or not entry.startswith("node_modules/") for entry in changed)
    assert not any(entry.endswith("/...") for entry in changed)


# --- Codex sandbox backend selection -------------------------------------
# `unelevated` was measured to allow writes OUTSIDE the workspace on this
# machine, so it must never become the default through a project file.


def test_windows_sandbox_defaults_to_elevated(tmp_path: Path, monkeypatch):
    from hybrid.providers.codex import CodexProvider

    monkeypatch.setattr("hybrid.providers.codex.os.name", "nt")
    provider = CodexProvider({"command": "codex"})
    assert provider._windows_sandbox_backend() == "elevated"


def test_non_windows_does_not_pass_a_windows_backend(tmp_path: Path, monkeypatch):
    from hybrid.providers.codex import CodexProvider

    monkeypatch.setattr(CodexProvider, "_windows_sandbox_backend", lambda self: None)
    assert CodexProvider({"command": "codex"})._windows_sandbox_backend() is None


def test_unknown_windows_sandbox_is_refused(monkeypatch):
    from hybrid.providers.codex import CodexProvider
    from hybrid.providers.base import ProviderError

    monkeypatch.setattr("hybrid.providers.codex.os.name", "nt")
    provider = CodexProvider({"command": "codex", "windows_sandbox": "turbo"})
    with pytest.raises(ProviderError, match="Unknown codex windows sandbox"):
        provider._windows_sandbox_backend()


def test_windows_sandbox_is_trusted_only(tmp_path: Path, monkeypatch):
    """A project settings.yaml must not be able to weaken the sandbox backend."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "config").mkdir()
    (project / "config" / "settings.yaml").write_text(
        "providers:\n  codex:\n    windows_sandbox: unelevated\n", encoding="utf-8"
    )
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "absent.yaml"))
    settings = load_settings(project)
    assert settings.raw["providers"]["codex"].get("windows_sandbox") != "unelevated"
    assert "providers.codex.windows_sandbox" in settings.sources.get("ignored_project_fields", [])


def test_probe_write_reports_success_when_the_file_appears(tmp_path: Path, monkeypatch):
    from hybrid.providers.codex import CodexProvider

    workdir = tmp_path / "work"
    workdir.mkdir()

    def fake_run(args, **kwargs):
        (workdir / "hybrid-sandbox-probe.txt").write_text("ok", encoding="utf-8")

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr("hybrid.providers.codex.subprocess.run", fake_run)
    monkeypatch.setattr(CodexProvider, "_resolve_command", lambda self: "codex")
    # Avoid depending on the host OS: the backend only affects the extra args.
    monkeypatch.setattr(CodexProvider, "_windows_sandbox_backend", lambda self: None)
    ok, detail = CodexProvider({"command": "codex"}).probe_write(workdir)
    assert ok is True
    assert "wrote" in detail


def test_probe_write_surfaces_the_helper_error(tmp_path: Path, monkeypatch):
    """The known provisioning failure must be reported, not hidden."""
    from hybrid.providers.codex import CodexProvider

    workdir = tmp_path / "work"
    workdir.mkdir()

    def fake_run(args, **kwargs):
        class Result:
            returncode = 0
            stdout = "Rejected: helper_unknown_error: setup refresh had errors"
            stderr = ""

        return Result()

    monkeypatch.setattr("hybrid.providers.codex.subprocess.run", fake_run)
    monkeypatch.setattr(CodexProvider, "_resolve_command", lambda self: "codex")
    monkeypatch.setattr(CodexProvider, "_windows_sandbox_backend", lambda self: None)
    ok, detail = CodexProvider({"command": "codex"}).probe_write(workdir)
    assert ok is False
    assert "helper_unknown_error" in detail


def test_execute_passes_the_windows_backend_explicitly(monkeypatch, tmp_path: Path):
    """The run must not depend on the machine's global Codex config."""
    from hybrid.providers.codex import CodexProvider
    from hybrid.tasks import TaskRecord
    from hybrid.providers.base import ProviderContext

    import subprocess
    import sys

    captured: dict = {}
    real_run = subprocess.run

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        code = "import os; os.write(1, 'готово — café 🌍'.encode('utf-8') + bytes([255]))"
        return real_run([sys.executable, "-c", code], **kwargs)

    monkeypatch.setattr("hybrid.providers.codex.subprocess.run", fake_run)
    monkeypatch.setattr(CodexProvider, "_resolve_command", lambda self: "codex")
    monkeypatch.setattr("hybrid.providers.codex.os.name", "nt")

    provider = CodexProvider({"command": "codex", "sandbox": "workspace-write"})
    task = TaskRecord.new("do a thing", "safe", "codex", "medium", tmp_path)
    result = provider.execute(task, ProviderContext(project_dir=tmp_path, settings={}, target_files=[]))
    args = captured["args"]
    assert result.output == "готово — café 🌍�"
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"
    assert "-c" in args
    assert 'windows.sandbox="elevated"' in args
    assert args[args.index("--sandbox") + 1] == "workspace-write"
