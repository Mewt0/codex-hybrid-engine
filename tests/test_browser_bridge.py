from __future__ import annotations

from pathlib import Path
import json

import pytest
import yaml

from hybrid.browser_bridge import BrowserBridge, BrowserBridgeError, BrowserTaskStore, ResponseAlreadyImported
from hybrid.browser_bridge.providers import get_provider
from hybrid.config import load_settings
from hybrid.controller import Controller
from test_engine import project, run


def trusted_config(tmp_path: Path, monkeypatch, allowed: list[str]) -> None:
    trusted = tmp_path / "trusted.yaml"
    trusted.write_text(yaml.safe_dump({"context": {"allowed_files": allowed}}), encoding="utf-8")
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(trusted))


@pytest.fixture()
def bridge(project: Path, tmp_path: Path, monkeypatch):
    trusted_config(tmp_path, monkeypatch, ["app.js", "index.php"])
    (project / "index.php").write_text("<?php echo 'hi';\n", encoding="utf-8")
    (project / ".env").write_text("SECRET=1\n", encoding="utf-8")
    assert run(["git", "add", "-A"], project).returncode == 0
    assert run(["git", "commit", "-m", "fixture"], project).returncode == 0
    settings = load_settings(project)
    controller = Controller(settings)
    return BrowserBridge(settings, controller), project, controller


ANSWER = """## SUMMARY
Fixed the label text.

## FILES
- app.js — label text

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

ANALYSIS_ONLY = """## SUMMARY
The panel needs a grid container and a media query.

## CHECKS
- none
"""


def test_prepare_creates_deepseek_task_without_network(bridge):
    bridge_obj, project, _ = bridge
    task = bridge_obj.prepare("Улучши игровую панель", "deepseek", "frontend")
    assert task.provider == "deepseek_web"
    assert task.profile == "frontend"
    assert task.url == "https://chat.deepseek.com"
    assert task.status == "WAITING_FOR_USER"
    assert Path(task.prompt_path).is_file()
    assert task.engine_task_id.startswith("TASK-")


def test_chatgpt_provider_uses_same_interface(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("Update the SQL query", "chatgpt", "database")
    assert task.provider == "chatgpt_web"
    assert task.url == "https://chatgpt.com"
    assert "chatgpt.com" in task.url
    provider = get_provider(task.provider)
    ok, detail = provider.available()
    assert ok and "relay" in detail


def test_unknown_provider_is_rejected(bridge):
    bridge_obj, _, _ = bridge
    with pytest.raises(BrowserBridgeError, match="Unknown browser provider"):
        bridge_obj.prepare("task", "gemini_web", None)


def test_prompt_contains_rules_and_no_access_notice(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("Сделай инвентарь", "deepseek_web", "frontend")
    prompt = bridge_obj.prompt(task.task_id)
    assert "REQUIRED ANSWER FORMAT" in prompt
    assert "NO access to the local filesystem" in prompt
    assert "legacy PHP" in prompt
    assert "## PATCH" in prompt


def test_prompt_never_contains_secrets_or_env(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("Сделай инвентарь", "deepseek_web", "fullstack-game")
    prompt = bridge_obj.prompt(task.task_id)
    assert "SECRET=1" not in prompt
    assert ".env" not in prompt


def test_prompt_contains_only_allowed_files(bridge):
    bridge_obj, project, _ = bridge
    task = bridge_obj.prepare("Сделай инвентарь", "deepseek_web", "fullstack-game")
    prompt = bridge_obj.prompt(task.task_id)
    assert "app.js" in prompt
    assert "index.php" in prompt


def test_import_unified_diff_reaches_review(bridge):
    bridge_obj, project, controller = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, ANSWER)
    assert record.status == "ready_for_review"
    assert record.changed_files == ["app.js"]
    assert record.checks["Patch Validation"]["status"] == "PASS"
    # Nothing was written to the project yet (.hybrid is engine state, ignored).
    assert run(["git", "status", "--porcelain", "app.js"], project).stdout.strip() == ""


def test_apply_requires_confirmation_and_worktree_check(bridge):
    bridge_obj, project, controller = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, ANSWER)
    with pytest.raises(RuntimeError, match="confirmation"):
        controller.apply(record.task_id)
    applied = controller.apply(record.task_id, confirm=True)
    assert applied.status == "applied"
    assert '"READY"' in (project / "app.js").read_text(encoding="utf-8")


def test_repeat_import_is_refused_without_force(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    bridge_obj.import_response(task.task_id, ANSWER)
    with pytest.raises(ResponseAlreadyImported):
        bridge_obj.import_response(task.task_id, ANSWER)


def test_force_import_resets_previous_review(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    first = bridge_obj.import_response(task.task_id, ANSWER)
    assert first.checks["Patch Validation"]["status"] == "PASS"
    second = bridge_obj.import_response(task.task_id, ANSWER.replace("READY", "FIXED"), force=True)
    assert second.import_count == 2
    assert second.status == "ready_for_review"
    assert "FIXED" in bridge_obj.diff(task.task_id)


def test_invalid_patch_is_rejected_and_not_applied(bridge):
    bridge_obj, project, _ = bridge
    broken = ANSWER.replace(
        '@@ -1 +1 @@\n-export const value = "BROKEN";',
        '@@ -1 +1 @@\n-export const value = "TOTALLY DIFFERENT";',
    )
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, broken)
    assert record.status == "failed"
    assert record.checks["Patch Validation"]["status"] == "FAIL"
    assert "BROKEN" in (project / "app.js").read_text(encoding="utf-8")


def test_patch_touching_protected_path_is_rejected(bridge):
    bridge_obj, _, _ = bridge
    hostile = ANSWER.replace("a/app.js", "a/.env").replace("b/app.js", "b/.env")
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, hostile)
    assert record.status == "failed"
    assert "Patch Paths" in record.checks


def test_analysis_only_response_is_stored_not_applied(bridge):
    bridge_obj, project, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, ANALYSIS_ONLY)
    assert record.status == "waiting_for_user"
    assert record.analysis.startswith("The panel needs")
    assert record.patch_sha256 is None
    assert run(["git", "status", "--porcelain", "app.js"], project).stdout.strip() == ""


def test_missing_response_is_reported(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    with pytest.raises(BrowserBridgeError, match="empty"):
        bridge_obj.import_response(task.task_id, "   ")


# --- review round: path collection, case handling, digest normalisation ------

DELETION_ANSWER = """## SUMMARY
Removed an unused secret file.

## PATCH
```diff
diff --git a/.env b/.env
deleted file mode 100644
index 1111111..0000000
--- a/.env
+++ /dev/null
@@ -1 +0,0 @@
-SECRET=1
```

## LIMITATIONS
- none
"""


def test_deletion_patch_cannot_smuggle_a_protected_path(bridge):
    """The old side of a deletion must be validated, not only the new side."""
    bridge_obj, project, _ = bridge
    task = bridge_obj.prepare("remove unused file", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, DELETION_ANSWER)
    assert record.status == "failed"
    assert record.checks["Patch Paths"]["status"] == "FAIL"
    assert ".env" in record.checks["Patch Paths"]["detail"]
    # Nothing was removed from the project.
    assert (project / ".env").exists()


def test_rename_patch_validates_both_sides(bridge):
    bridge_obj, _, _ = bridge
    rename = ANSWER.replace("a/app.js b/app.js", "a/app.js b/config/secrets/app.js")
    task = bridge_obj.prepare("move file", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, rename)
    assert record.status == "failed"
    assert record.checks["Patch Paths"]["status"] == "FAIL"


def test_protected_paths_are_matched_case_insensitively(bridge):
    bridge_obj, _, _ = bridge
    hostile = ANSWER.replace("a/app.js b/app.js", "a/CONFIG/SECRETS/key.php b/CONFIG/SECRETS/key.php")
    task = bridge_obj.prepare("touch config", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, hostile)
    assert record.status == "failed"
    assert "protected path" in record.checks["Patch Paths"]["detail"].lower()


def test_windows_style_separators_are_normalised(bridge):
    bridge_obj, _, _ = bridge
    windows_style = ANSWER.replace("a/app.js b/app.js", "a/.hybrid\\tasks\\x b/.hybrid\\tasks\\x")
    task = bridge_obj.prepare("touch engine state", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, windows_style)
    assert record.status == "failed"


def test_crlf_copy_of_the_same_answer_counts_as_the_same_import(bridge):
    """A CRLF paste of the same answer must not look like a new import."""
    from hybrid.browser_bridge import BrowserTaskStore, BrowserTask

    bridge_obj, _, _ = bridge
    store = BrowserTaskStore(bridge_obj.settings.data_dir)
    task = BrowserTask.new("deepseek_web", "fix label", "frontend", "https://chat.deepseek.com")
    store.save(task)
    store.import_response(task.task_id, ANSWER)
    crlf_copy = ANSWER.replace("\n", "\r\n")
    with pytest.raises(ResponseAlreadyImported, match="Identical response"):
        store.import_response(task.task_id, crlf_copy)


def test_bridge_refuses_any_second_import_without_force(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    bridge_obj.import_response(task.task_id, ANSWER)
    with pytest.raises(ResponseAlreadyImported, match="already has a validated result"):
        bridge_obj.import_response(task.task_id, ANSWER.replace("\n", "\r\n"))


def test_stored_digest_matches_the_review_payload(bridge):
    import hashlib

    from hybrid.browser_bridge import BrowserTaskStore

    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, ANSWER)
    store = BrowserTaskStore(bridge_obj.settings.data_dir)
    stored = store.response_file(task.task_id).read_text(encoding="utf-8")
    expected = hashlib.sha256(stored.encode("utf-8")).hexdigest()
    assert record.response_sha256 == expected
    assert bridge_obj.review_payload(task.task_id)["status"] == "ready_for_review"


def test_state_survives_restart(bridge):
    bridge_obj, project, controller = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    bridge_obj.import_response(task.task_id, ANSWER)

    settings = load_settings(project)
    reopened = BrowserBridge(settings, Controller(settings))
    restored = reopened.task(task.task_id)
    assert restored.status == "waiting_for_user" or restored.engine_task_id
    payload = reopened.review_payload(task.task_id)
    assert payload["status"] == "ready_for_review"
    assert payload["changed_files"] == ["app.js"]


def test_review_request_targets_the_other_provider(bridge):
    bridge_obj, _, _ = bridge
    first = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    bridge_obj.import_response(first.task_id, ANSWER)
    review_task = bridge_obj.prepare_review(first.task_id)
    assert review_task.provider == "chatgpt_web"
    prompt = bridge_obj.prompt(review_task.task_id)
    assert "INDEPENDENT REVIEW REQUEST" in prompt
    assert "Fixed the label text." in prompt


def test_history_and_cancel(bridge):
    bridge_obj, _, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    assert [item.task_id for item in bridge_obj.history()] == [task.task_id]
    cancelled = bridge_obj.cancel(task.task_id)
    assert cancelled.status == "CANCELLED"


def test_no_api_keys_are_required(bridge, monkeypatch):
    bridge_obj, _, _ = bridge
    for name in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    record = bridge_obj.import_response(task.task_id, ANSWER)
    assert record.status == "ready_for_review"


def test_review_file_is_written(bridge):
    bridge_obj, project, _ = bridge
    task = bridge_obj.prepare("fix label", "deepseek_web", "frontend")
    bridge_obj.import_response(task.task_id, ANSWER)
    store = BrowserTaskStore(bridge_obj.settings.data_dir)
    payload = json.loads(store.review_file(task.task_id).read_text(encoding="utf-8"))
    assert payload["stage"] == "patch_validated"
    assert payload["applied"] is False
    assert payload["is_patch"] is True
