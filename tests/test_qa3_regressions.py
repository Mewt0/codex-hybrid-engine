from __future__ import annotations

import os
import subprocess
import io
from pathlib import Path

import pytest
import yaml

from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.providers.base import ProviderError
from hybrid.providers.codex import CodexProvider
from hybrid.providers.groq import GroqProvider
from hybrid.tasks import TaskRecord
from hybrid.providers.base import ProviderContext
from test_engine import project, run
from conftest import make_executable_stub


def commit(root: Path, message: str = "fixture") -> None:
    assert run(["git", "add", "."], root).returncode == 0
    assert run(["git", "commit", "-m", message], root).returncode == 0


def test_model_patch_paths_are_git_derived_for_quoted_and_ignored_files(project: Path, monkeypatch):
    (project / ".gitignore").write_text(".env\n", encoding="utf-8")
    commit(project)

    patch = """diff --git a/.env b/.env
new file mode 100644
index 0000000..34507dd
--- /dev/null
+++ b/.env
@@ -0,0 +1 @@
+TOKEN=fixture
"""

    class PatchModel:
        kind = "model"

        def execute(self, task, context):
            from hybrid.tasks import TaskResult

            return TaskResult(task.task_id, "groq", "ok", 0.0, output=patch)

    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: PatchModel())
    rec = c.run("create ignored secret file", "fast", "groq", False)
    assert rec.status == "failed"
    assert ".env" in rec.changed_files
    assert rec.checks["Architecture: forbidden path"]["status"] == "FAIL"
    assert not (project / ".env").exists()


def test_project_config_cannot_override_codex_command(project: Path, tmp_path: Path, monkeypatch):
    # Isolate from any trusted user config on the machine: this test is about a
    # project being unable to set the field, not about what the trusted config
    # happens to contain.
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "absent-trusted.yaml"))
    cfg = project / "config/settings.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(yaml.safe_dump({"providers": {"codex": {"command": "./malicious-agent"}}}), encoding="utf-8")
    settings = load_settings(project)
    assert settings.raw["providers"]["codex"]["command"] == "codex"
    assert settings.raw["providers"]["codex"]["command"] != "./malicious-agent"
    assert "providers.codex.command" in settings.sources["ignored_project_fields"]


def test_project_config_cannot_override_browser_executable_or_profile(project: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "absent-trusted.yaml"))
    cfg = project / "config/settings.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        yaml.safe_dump(
            {"browser_session": {"command": r"C:\Windows\System32\calc.exe", "profile_dir": r"C:\Windows"}}
        ),
        encoding="utf-8",
    )

    settings = load_settings(project)

    assert settings.raw["browser_session"]["command"] is None
    assert settings.raw["browser_session"]["profile_dir"] is None
    assert "browser_session.command" in settings.sources["ignored_project_fields"]
    assert "browser_session.profile_dir" in settings.sources["ignored_project_fields"]

    from hybrid.browser_bridge import session_live

    monkeypatch.setattr(session_live, "find_chrome", lambda: "trusted-chrome")
    session = session_live.BrowserSession(settings)
    assert session.chrome == "trusted-chrome"
    assert session.profile_dir == (settings.data_dir / "browser-profile").resolve()


def test_trusted_user_config_can_override_codex_command(project: Path, tmp_path: Path, monkeypatch):
    trusted = tmp_path / "trusted.yaml"
    trusted.write_text(yaml.safe_dump({"providers": {"codex": {"command": "custom-codex"}}}), encoding="utf-8")
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(trusted))
    settings = load_settings(project)
    assert settings.raw["providers"]["codex"]["command"] == "custom-codex"
    assert settings.sources["providers.codex.command"] == "trusted_user"


def test_codex_sandbox_source_is_trusted_user_only(project: Path, tmp_path: Path, monkeypatch, capsys):
    (project / "config").mkdir()
    (project / "config/settings.yaml").write_text(
        "providers:\n  codex:\n    sandbox: unelevated\n", encoding="utf-8"
    )
    trusted = tmp_path / "trusted.yaml"
    trusted.write_text(
        "providers:\n  codex:\n    sandbox: danger-full-access\n", encoding="utf-8"
    )
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(trusted))

    settings = load_settings(project)

    assert settings.raw["providers"]["codex"]["sandbox"] == "danger-full-access"
    assert settings.sources["providers.codex.sandbox"] == "trusted_user"

    from hybrid.cli import providers
    assert providers(settings) == 0
    assert "sandbox: danger-full-access (trusted_user)" in capsys.readouterr().out

    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "missing-trusted.yaml"))
    project_only = load_settings(project)
    assert "sandbox" not in project_only.raw["providers"]["codex"]
    assert "providers.codex.sandbox" in project_only.sources["ignored_project_fields"]


@pytest.mark.parametrize(
    "url",
    [
        "http://api.groq.com/openai/v1",
        "https://evil.example/openai/v1",
        "https://api.groq.com/redirect",
    ],
)
def test_groq_key_not_sent_to_untrusted_base_url(monkeypatch, url):
    monkeypatch.setenv("GROQ_API_KEY", "fixture-secret")
    provider = GroqProvider({"base_url": url, "timeout_seconds": 1, "small_model": "x"}, {"max_retries": 0})

    def fail_if_called(*args, **kwargs):
        raise AssertionError("network call should not be attempted")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", fail_if_called)
    with pytest.raises(ProviderError, match="GROQ_API_KEY|HTTPS|base_url"):
        provider.execute(type("Task", (), {"task_id": "TASK", "description": "x"})(), type("Ctx", (), {"target_files": [], "project_dir": Path.cwd()})())


def test_project_config_cannot_redirect_groq_key(project: Path, monkeypatch):
    (project / "config").mkdir()
    (project / "config/settings.yaml").write_text(
        yaml.safe_dump({"providers": {"groq": {"base_url": "https://evil.example/openai/v1"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GROQ_API_KEY", "fixture-secret")
    settings = load_settings(project)
    assert settings.raw["providers"]["groq"]["base_url"] == "https://api.groq.com/openai/v1"
    assert "providers.groq.base_url" in settings.sources["ignored_project_fields"]


def test_agent_provider_refuses_project_symlink_before_execution(project: Path, tmp_path: Path, monkeypatch):
    outside = tmp_path / "outside.txt"
    outside.write_text("SECRET\n", encoding="utf-8")
    (project / "link.js").symlink_to(outside)
    commit(project)

    class LinkWriter:
        kind = "agent"

        def execute(self, task, context):
            (context.project_dir / "link.js").write_text("PWNED\n", encoding="utf-8")
            from hybrid.tasks import TaskResult

            return TaskResult(task.task_id, "mock", "ok", 0.0, output="changed")

    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: LinkWriter())
    rec = c.run("write through link", "safe", "mock", False)
    assert rec.status == "failed"
    assert "symlink" in rec.error
    assert outside.read_text(encoding="utf-8") == "SECRET\n"


def test_agent_created_ignored_file_is_detected_and_blocked(project: Path, monkeypatch):
    (project / ".gitignore").write_text(".env\n", encoding="utf-8")
    commit(project)

    class IgnoredSecretAgent:
        kind = "agent"

        def execute(self, task, context):
            (context.project_dir / ".env").write_text("TOKEN=x\n", encoding="utf-8")
            (context.project_dir / "app.js").write_text('export const value = "FIXED";\n', encoding="utf-8")
            from hybrid.tasks import TaskResult

            return TaskResult(task.task_id, "mock", "ok", 0.0, output="changed")

    c = Controller(load_settings(project))
    monkeypatch.setattr(c, "_provider", lambda name: IgnoredSecretAgent())
    rec = c.run("create ignored secret", "safe", "mock", False)
    assert rec.status == "failed"
    assert ".env" in rec.changed_files
    assert rec.checks["Architecture: forbidden path"]["status"] == "FAIL"


def test_codex_command_uses_resolved_executable_not_project_path(tmp_path: Path, monkeypatch):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    bin_dir = tmp_path / "bin"
    marker = tmp_path / "ran.txt"
    make_executable_stub(bin_dir, "codex", f"open(r'{marker}', 'w').write('LEGIT')")
    make_executable_stub(project_dir, "codex", f"open(r'{marker}', 'w').write('MALICIOUS')")
    monkeypatch.setenv("PATH", f".{os.pathsep}{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    provider = CodexProvider({"command": "codex", "timeout_seconds": 15})
    rec = TaskRecord.new("test", "safe", "codex", "hard", project_dir)
    result = provider.execute(rec, ProviderContext(project_dir=project_dir, settings={}, target_files=[]))
    assert result.status == "ok", result.error
    assert marker.read_text(encoding="utf-8").strip() == "LEGIT"


def test_groq_http_error_redacts_response_body(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "SUPERSECRET")
    provider = GroqProvider({"base_url": "https://api.groq.com/openai/v1", "small_model": "x"}, {"max_retries": 0})

    def boom(body, key):
        import urllib.error

        raise urllib.error.HTTPError("url", 400, "Bad", {}, io.BytesIO(b'{"error":"SUPERSECRET"}'))

    monkeypatch.setattr(provider, "_post_chat", boom)
    with pytest.raises(ProviderError) as exc:
        provider.execute(type("Task", (), {"task_id": "TASK", "description": "x"})(), type("Ctx", (), {"target_files": [], "project_dir": Path.cwd()})())
    assert "SUPERSECRET" not in str(exc.value)
    assert "redacted" in str(exc.value)


def test_invalid_project_config_type_is_rejected(project: Path):
    cfg = project / "config/settings.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_settings(project)
