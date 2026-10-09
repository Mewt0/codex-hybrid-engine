from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.providers.codex import CodexProvider
from hybrid.providers.base import ProviderContext
from hybrid.tasks import TaskRecord, TaskResult
from test_engine import project, run
from conftest import make_executable_stub


def commit(root: Path, message: str = "fixture") -> None:
    assert run(["git", "add", "."], root).returncode == 0
    assert run(["git", "commit", "-m", message], root).returncode == 0


def test_project_config_cannot_remove_mandatory_env_protection(project: Path):
    cfg = project / "config/settings.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        yaml.safe_dump({"architecture": {"forbidden_paths": []}}),
        encoding="utf-8",
    )
    settings = load_settings(project)
    assert ".env" in settings.raw["architecture"]["forbidden_paths"]

    class EnvAgent:
        kind = "agent"

        def execute(self, task, context):
            (context.project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
            return TaskResult(task.task_id, "mock", "ok", 0.0, output="changed")

    c = Controller(settings)
    c._provider = lambda name: EnvAgent()
    rec = c.run("create env", "safe", "mock", False)
    assert rec.status == "failed"
    assert ".env" in rec.changed_files


def test_ignored_directory_contents_are_detected(project: Path, monkeypatch):
    (project / ".gitignore").write_text("cache/\n", encoding="utf-8")
    commit(project)

    class CacheAgent:
        kind = "agent"

        def execute(self, task, context):
            (context.project_dir / "cache/private").mkdir(parents=True)
            (context.project_dir / "cache/private/token.txt").write_text("TOKEN=x\n", encoding="utf-8")
            (context.project_dir / "app.js").write_text('export const value = "FIXED";\n', encoding="utf-8")
            return TaskResult(task.task_id, "mock", "ok", 0.0, output="changed")

    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: CacheAgent())
    rec = c.run("edit app and create ignored dir", "safe", "mock", False)
    assert rec.status == "failed"
    assert "cache/private/token.txt" in rec.changed_files
    assert rec.checks["Architecture: sensitive path"]["status"] == "FAIL"


def test_codex_env_does_not_forward_provider_api_keys(tmp_path: Path, monkeypatch):
    marker = tmp_path / "env.txt"
    payload = (
        "open(r'%s','w').write(repr(sorted(k for k in __import__('os').environ "
        "if k.endswith('_API_KEY') or k in ('OPENAI_API_KEY', 'GROQ_API_KEY'))))"
    ) % marker
    command = make_executable_stub(tmp_path, "codex", payload)
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    monkeypatch.setenv("GROQ_API_KEY", "groq-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")

    provider = CodexProvider({"command": str(command), "timeout_seconds": 15})
    rec = TaskRecord.new("inspect env", "safe", "codex", "hard", project_dir)
    result = provider.execute(rec, ProviderContext(project_dir=project_dir, settings={}, target_files=[]))
    assert result.status == "ok", result.error
    assert marker.read_text(encoding="utf-8").strip() == "[]"


def test_project_allowed_files_cannot_grant_cloud_context(project: Path):
    cfg = project / "config/settings.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(yaml.safe_dump({"context": {"allowed_files": ["app.js"]}}), encoding="utf-8")
    c = Controller(load_settings(project))
    assert c.settings.raw["context"]["allowed_files"] == []
    assert c._target_files(project, cloud=True) == []


def test_trusted_allowed_files_can_be_narrowed_by_project(project: Path, tmp_path: Path, monkeypatch):
    trusted = tmp_path / "trusted.yaml"
    trusted.write_text(yaml.safe_dump({"context": {"allowed_files": ["app.js", "README.md"]}}), encoding="utf-8")
    cfg = project / "config/settings.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(yaml.safe_dump({"context": {"allowed_files": ["app.js"]}}), encoding="utf-8")
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(trusted))

    c = Controller(load_settings(project))
    rels = [path.relative_to(project).as_posix() for path in c._target_files(project, cloud=True)]
    assert rels == ["app.js"]
