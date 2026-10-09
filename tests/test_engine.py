from __future__ import annotations

import json
import subprocess
from pathlib import Path
import pytest
from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.providers.groq import GroqProvider
from hybrid.providers.base import ProviderError
from hybrid.providers.mock import MockPatchProvider
from hybrid.tasks import TaskResult
from hybrid.quality.checks import validate_paths, run_quality


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


@pytest.fixture()
def project(tmp_path: Path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.js").write_text('export const value = "BROKEN";\n', encoding="utf-8")
    run(["git", "init"], root)
    run(["git", "config", "user.email", "test@example.invalid"], root)
    run(["git", "config", "user.name", "Test"], root)
    run(["git", "add", "."], root)
    run(["git", "commit", "-m", "init"], root)
    monkeypatch.setenv("HYBRID_DATA_DIR", str(root / ".hybrid"))
    return root


def test_fast_mode_never_modifies_project_before_approval(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("fix small label", "fast", "mock", dry_run=False)
    assert rec.status == "ready_for_review"
    assert rec.approved is False
    assert "app.js" in rec.changed_files
    assert run(["git", "status", "--porcelain"], project).stdout.strip() == ""
    assert "BROKEN" in (project / "app.js").read_text(encoding="utf-8")


def test_safe_mode_creates_separate_worktree(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("fix small label", "safe", "mock", dry_run=False)
    assert rec.worktree_dir
    assert Path(rec.worktree_dir).exists()
    assert (project / "app.js").read_text(encoding="utf-8").count("BROKEN") == 1


def test_forbidden_file_cannot_change(project: Path):
    result = validate_paths(project, [".env"], {"forbidden_paths": [".env"], "max_files_changed": 5})
    assert any(r.status == "FAIL" for r in result)


def test_invalid_patch_is_not_applied(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("fix small label", "fast", "mock", dry_run=False)
    patch = Path(rec.artifact_dir) / "proposed.patch"
    patch.write_text("not a patch", encoding="utf-8")
    with pytest.raises(Exception):
        c.apply(rec.task_id, confirm=True)
    assert "BROKEN" in (project / "app.js").read_text(encoding="utf-8")


def test_groq_missing_key_message(monkeypatch, project: Path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = GroqProvider({"base_url": "https://api.groq.com/openai/v1"}, {"max_retries": 1, "allow_paid_api": False})
    ok, detail = provider.available()
    assert not ok
    assert "GROQ_API_KEY" in detail


def test_dry_run_persists_history(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("update css color", "safe", None, dry_run=True)
    data = json.loads((project / ".hybrid" / "tasks.json").read_text(encoding="utf-8"))
    assert rec.task_id in data["tasks"]
    assert data["tasks"][rec.task_id]["provider"] == "groq"


def test_js_syntax_error_detected(project: Path):
    (project / "app.js").write_text("function {\n", encoding="utf-8")
    results = run_quality(project, ["app.js"])
    assert any(r.name.startswith("JS Syntax") and r.status == "FAIL" for r in results)


def test_parent_traversal_and_symlink_boundary(project: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = project / "leak.txt"
    link.symlink_to(outside)
    results = validate_paths(project, ["../x", "leak.txt"], {"forbidden_paths": [], "max_files_changed": 5})
    assert sum(r.status == "FAIL" for r in results) >= 2


def test_cloud_disabled_cli_still_plans(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("change css", "fast", None, dry_run=True)
    assert rec.provider == "groq"
    assert rec.status == "planned"


def test_english_docs_route_to_low_cost_provider(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("update docs", "fast", None, dry_run=True)
    assert rec.provider == "groq"


def test_429_wrapped(monkeypatch, project: Path):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    provider = GroqProvider({"base_url": "https://api.groq.com/openai/v1", "timeout_seconds": 1, "small_model": "x"}, {"max_retries": 0})
    def boom(*args, **kwargs):
        import urllib.error
        raise urllib.error.HTTPError("url", 429, "Too Many", {}, None)
    monkeypatch.setattr(provider, "_post_chat", boom)
    rec = Controller(load_settings(project)).plan("doc", "fast", "groq")
    with pytest.raises(ProviderError, match="429"):
        provider.execute(rec, type("Ctx", (), {"target_files": [], "project_dir": project})())


def test_apply_requires_confirmation(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("fix small label", "safe", "mock", dry_run=False)
    with pytest.raises(RuntimeError, match="confirmation"):
        c.apply(rec.task_id)
    assert "BROKEN" in (project / "app.js").read_text(encoding="utf-8")


def test_apply_after_confirmation_and_repeat_rejected(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("fix small label", "safe", "mock", dry_run=False)
    applied = c.apply(rec.task_id, confirm=True)
    assert applied.status == "applied"
    assert "FIXED" in (project / "app.js").read_text(encoding="utf-8")
    with pytest.raises(RuntimeError, match="already"):
        c.apply(rec.task_id, confirm=True)


class FailingProvider(MockPatchProvider):
    name = "failing"
    def execute(self, task, context):
        return TaskResult(task.task_id, self.name, "error", 0.01, output="", error="Simulated failure")


def test_failed_provider_cannot_be_ready_for_review(project: Path, monkeypatch):
    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: FailingProvider())
    rec = c.run("fix small label", "safe", "mock", dry_run=False)
    assert rec.status == "failed"
    assert "Simulated failure" in rec.error


class NewFileProvider(MockPatchProvider):
    name = "newfile"
    def execute(self, task, context):
        (context.project_dir / "new_feature.js").write_text("export const added = true;\n", encoding="utf-8")
        return TaskResult(task.task_id, self.name, "ok", 0.01, output="created")


def test_new_files_are_detected(project: Path, monkeypatch):
    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: NewFileProvider())
    rec = c.run("add new js file", "safe", "mock", dry_run=False)
    assert rec.status == "ready_for_review"
    assert "new_feature.js" in rec.changed_files
    assert "new_feature.js" in c.diff(rec.task_id)


def test_no_auto_git_init_without_consent(tmp_path: Path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "app.js").write_text("const x = 1;\n", encoding="utf-8")
    monkeypatch.setenv("HYBRID_DATA_DIR", str(root / ".hybrid"))
    c = Controller(load_settings(root))
    rec = c.run("fix", "safe", "mock", dry_run=False)
    assert rec.status == "failed"
    assert "not a Git repository" in rec.error
    assert not (root / ".git").exists()


def test_context_excludes_forbidden_and_secret_files(project: Path):
    (project / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (project / "config").mkdir()
    (project / "config" / "secrets.js").write_text("export const token='x';\n", encoding="utf-8")
    (project / "safe.js").write_text("export const ok = true;\n", encoding="utf-8")
    c = Controller(load_settings(project))
    rels = {p.relative_to(project).as_posix() for p in c._target_files(project)}
    assert "safe.js" in rels
    assert ".env" not in rels
    assert "config/secrets.js" not in rels


def test_apply_detects_project_changes_after_review(project: Path):
    c = Controller(load_settings(project))
    rec = c.run("fix small label", "safe", "mock", dry_run=False)
    (project / "app.js").write_text('export const value = "USER CHANGE";\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="local changes"):
        c.apply(rec.task_id, confirm=True)


def test_patches_are_per_task(project: Path):
    c = Controller(load_settings(project))
    first = c.run("fix small label", "safe", "mock", dry_run=False)
    second = c.run("fix small label again", "safe", "mock", dry_run=False)
    assert Path(first.artifact_dir) != Path(second.artifact_dir)
    assert (Path(first.artifact_dir) / "proposed.patch").exists()
    assert (Path(second.artifact_dir) / "proposed.patch").exists()


class BadPatchModelProvider(MockPatchProvider):
    name = "badpatch"
    kind = "model"
    def execute(self, task, context):
        return TaskResult(task.task_id, self.name, "ok", 0.01, output="not a patch")


class SecretProbeProvider(MockPatchProvider):
    name = "secretprobe"
    kind = "agent"
    seen_secret = False
    def execute(self, task, context):
        self.seen_secret = (context.project_dir / ".env").exists() or (context.project_dir / "secret-token.js").exists()
        (context.project_dir / "app.js").write_text('export const value = "FIXED";\n', encoding="utf-8")
        return TaskResult(task.task_id, self.name, "ok", 0.01, output="changed")


def test_model_provider_invalid_patch_cannot_be_ready_for_review(project: Path, monkeypatch):
    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: BadPatchModelProvider())
    rec = c.run("return bad patch", "fast", "groq", dry_run=False)
    assert rec.status == "failed"
    assert rec.checks["Patch Validation"]["status"] == "FAIL"


def test_fast_agent_temp_copy_excludes_secret_files(project: Path, monkeypatch):
    (project / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (project / "secret-token.js").write_text("export const token='secret';\n", encoding="utf-8")
    provider = SecretProbeProvider()
    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: provider)
    rec = c.run("fix without secrets", "fast", "mock", dry_run=False)
    assert rec.status == "ready_for_review"
    assert provider.seen_secret is False

