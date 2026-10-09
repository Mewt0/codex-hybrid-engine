"""Reconstructed regressions from the audit; original attachment was unavailable."""
import json
from pathlib import Path

import pytest

from test_engine import project, run
from hybrid.controller import Controller
from hybrid.config import load_settings
from hybrid.tasks import TaskResult
from hybrid.providers.base import ProviderError
from hybrid.quality.checks import run_quality


def controller(project, monkeypatch, action):
    c = Controller(load_settings(project))
    class Agent:
        kind = "agent"
        def execute(self, task, context):
            action(context.project_dir)
            return TaskResult(task.task_id, "mock", "ok", 0.0)
    monkeypatch.setattr(c, "_provider", lambda name: Agent())
    return c


def commit(root):
    assert run(["git", "add", "."], root).returncode == 0
    assert run(["git", "commit", "-m", "fixture"], root).returncode == 0


@pytest.mark.parametrize("operation", ["rename", "delete"])
def test_protected_source_blocked(project, monkeypatch, operation):
    p = project / "tests/protected/locked.js"
    p.parent.mkdir(parents=True)
    p.write_text("const locked = 1;\n")
    commit(project)
    def action(root):
        if operation == "rename":
            (root / "visible").mkdir()
            assert run(["git", "mv", "tests/protected/locked.js", "visible/locked.js"], root).returncode == 0
        else:
            (root / "tests/protected/locked.js").unlink()
    c = controller(project, monkeypatch, action)
    rec = c.run("move file", "safe", "mock", False)
    assert rec.status == "failed"
    assert "tests/protected/locked.js" in rec.changed_files
    with pytest.raises(RuntimeError):
        c.apply(rec.task_id, confirm=True)
    assert p.exists()


def test_cloud_context_requires_explicit_allowlist(project):
    (project / "config").mkdir()
    (project / "config/db.php").write_text("<?php $password = 'fixture';")
    c = Controller(load_settings(project))
    c.settings.raw = dict(c.settings.raw, context={"allowed_files": ["app.js", "config/db.php"]})
    files = c._target_files(project, cloud=True)
    assert [p.relative_to(project).as_posix() for p in files] == ["app.js"]
    assert "config/db.php" not in [p.relative_to(project).as_posix() for p in c._target_files(project)]
    c.settings.raw["context"]["allowed_files"] = []
    assert c._target_files(project, cloud=True) == []


@pytest.mark.parametrize("mode", ["fast", "safe"])
def test_nested_new_file_full_cycle(project, monkeypatch, mode):
    def action(root):
        (root / "newdir/sub").mkdir(parents=True)
        (root / "newdir/sub/feature.js").write_text("const feature = true;\n")
    c = controller(project, monkeypatch, action)
    rec = c.run("add feature", mode, "mock", False)
    assert rec.status == "ready_for_review", rec.checks
    assert rec.changed_files == ["newdir/sub/feature.js"]
    assert "newdir/sub/feature.js" in c.diff(rec.task_id)
    assert not (project / "newdir").exists()
    with pytest.raises(RuntimeError, match="confirmation"):
        c.apply(rec.task_id)
    assert c.apply(rec.task_id, confirm=True).status == "applied"
    assert (project / "newdir/sub/feature.js").exists()


def test_disabled_provider_blocked_before_execution(project, monkeypatch):
    c = Controller(load_settings(project))
    c.settings.raw = dict(c.settings.raw, providers={"groq": {"enabled": False}})
    with pytest.raises(ProviderError, match="disabled"):
        c._provider("groq")
    monkeypatch.setattr(c, "_provider", lambda name: pytest.fail("provider constructed"))
    for forced in [None, "groq"]:
        rec = c.run("update css", "fast", forced, False)
        assert rec.status == "failed"
        assert "disabled" in rec.error


@pytest.mark.parametrize("manifest,section", [("package.json", "dependencies"), ("composer.json", "require")])
@pytest.mark.parametrize("add", [True, False])
def test_dependency_policy(project, monkeypatch, manifest, section, add):
    (project / manifest).write_text(json.dumps({"description": "before"}))
    commit(project)
    def action(root):
        data = {"description": "after"}
        if add:
            data[section] = {"new-package": "*"}
        (root / manifest).write_text(json.dumps(data) + "\n")
    c = controller(project, monkeypatch, action)
    rec = c.run("edit manifest", "safe", "mock", False)
    assert rec.status == ("failed" if add else "ready_for_review"), rec.checks


def test_apply_rechecks_dependency_policy(project, monkeypatch):
    def action(root):
        (root / "package.json").write_text('{"dependencies":{"new-package":"*"}}\n')
    c = controller(project, monkeypatch, action)
    c.settings.raw = dict(c.settings.raw, architecture=dict(c.settings.raw["architecture"], allow_new_dependencies=True))
    rec = c.run("add package", "safe", "mock", False)
    assert rec.status == "ready_for_review"
    c.settings.raw["architecture"]["allow_new_dependencies"] = False
    with pytest.raises(RuntimeError, match="validation"):
        c.apply(rec.task_id, confirm=True)
    assert not (project / "package.json").exists()


def test_missing_php_is_skip(project, monkeypatch):
    (project / "demo.php").write_text("<?php echo 1;")
    # `run_quality` resolves PHP through `resolve_php` (which also honours
    # composer.json / .php-version), so that is the honest place to simulate a
    # host without PHP. The test host may well have one installed.
    monkeypatch.setattr("hybrid.quality.checks.resolve_php", lambda project_dir=None: None)
    checks = run_quality(project, ["demo.php"])
    assert next(c for c in checks if c.name == "PHP Syntax").status == "SKIP"


def test_php_binary_detection_reports_a_path_or_none():
    from hybrid.quality.checks import php_binary

    found = php_binary()
    assert found is None or "php" in found.lower()
