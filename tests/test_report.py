from __future__ import annotations

import json
from pathlib import Path

import pytest

from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.report import NOT_RUN, REPORT_FIELDS, ReportBuilder
from hybrid.tasks import TaskRecord
from test_engine import project, run


def make_record(project: Path, **overrides) -> TaskRecord:
    record = TaskRecord.new("fix small label", "safe", "mock", "easy", project)
    record.artifact_dir = str(project / ".hybrid" / "tasks" / record.task_id)
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


def test_report_contains_every_required_field(project: Path):
    controller = Controller(load_settings(project))
    record = make_record(project, status="ready_for_review")
    controller.store.save(record)
    report = ReportBuilder(controller.settings, controller).build(record.task_id)
    for name in REPORT_FIELDS:
        assert name in report.fields
    markdown = report.render_markdown()
    for name in REPORT_FIELDS:
        assert f"**{name}:**" in markdown


def test_unexecuted_checks_are_not_run_not_silent(project: Path):
    controller = Controller(load_settings(project))
    record = make_record(project)
    controller.store.save(record)
    report = ReportBuilder(controller.settings, controller).build(record.task_id)
    assert report.fields["PHP Checks"] == NOT_RUN
    assert report.fields["Browser QA"] == NOT_RUN
    assert report.fields["Responsive QA"] == NOT_RUN
    # An empty list renders as NOT RUN in the report text.
    assert report.fields["Screenshots"] == []
    assert "**Screenshots:** NOT RUN" in report.render_markdown()


def test_checks_are_summarized_by_language(project: Path):
    controller = Controller(load_settings(project))
    record = make_record(
        project,
        checks={
            "JS Syntax: app.js": {"status": "PASS", "detail": ""},
            "PHP Syntax: index.php": {"status": "FAIL", "detail": "syntax error"},
            "Git Diff": {"status": "PASS", "detail": ""},
        },
    )
    controller.store.save(record)
    report = ReportBuilder(controller.settings, controller).build(record.task_id)
    assert "JS Syntax: app.js" in report.fields["JavaScript Checks"]
    assert "PASS" in report.fields["JavaScript Checks"]
    assert "FAIL" in report.fields["PHP Checks"]
    assert any("syntax error" in item for item in report.fields["Errors"])


def test_approval_status_reflects_state(project: Path):
    controller = Controller(load_settings(project))
    builder = ReportBuilder(controller.settings, controller)
    stages = {
        "ready_for_review": "PENDING REVIEW",
        "applied": "APPLIED (confirmed by user)",
        "waiting_for_user": "NOT SUBMITTED",
    }
    for status, expected in stages.items():
        record = make_record(project, status=status)
        controller.store.save(record)
        assert builder.build(record.task_id).fields["Approval Status"] == expected


def test_report_files_are_written_with_lf(project: Path):
    controller = Controller(load_settings(project))
    record = make_record(project, changed_files=["app.js"], skills=["beautiful-game-ui"])
    controller.store.save(record)
    report = ReportBuilder(controller.settings, controller).build(record.task_id)
    assert report.json_path and report.json_path.is_file()
    assert report.markdown_path and report.markdown_path.is_file()
    assert b"\r\n" not in report.markdown_path.read_bytes()
    payload = json.loads(report.json_path.read_text(encoding="utf-8"))
    assert payload["task_id"] == record.task_id
    assert payload["fields"]["Skills Used"] == ["beautiful-game-ui"]


def test_visual_results_are_picked_up_when_present(project: Path):
    controller = Controller(load_settings(project))
    record = make_record(project)
    controller.store.save(record)
    visual_dir = Path(record.artifact_dir) / "visual"
    visual_dir.mkdir(parents=True, exist_ok=True)
    (visual_dir / "report.json").write_text(
        json.dumps(
            {
                "checks": [
                    {"name": "Console Errors", "status": "PASS", "detail": "0 errors"},
                    {"name": "Responsive", "status": "FAIL", "detail": "mobile missing"},
                    {"name": "Browser Driver", "status": "PASS", "detail": "agent-browser"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (visual_dir / "desktop.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    report = ReportBuilder(controller.settings, controller).build(record.task_id)
    assert "PASS" in report.fields["Browser QA"]
    assert "FAIL" in report.fields["Responsive QA"]
    assert any("desktop.png" in item for item in report.fields["Screenshots"])


def test_unknown_task_raises(project: Path):
    controller = Controller(load_settings(project))
    with pytest.raises(KeyError, match="Unknown task"):
        ReportBuilder(controller.settings, controller).build("TASK-DOESNOTEXIST")


def test_cli_report_command(project: Path, capsys):
    from hybrid import cli

    controller = Controller(load_settings(project))
    record = make_record(project, status="ready_for_review")
    controller.store.save(record)
    exit_code = cli.main(["--project", str(project), "report", record.task_id])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "TASK RESULT" in output
    assert record.task_id in output


def test_report_end_to_end_after_run(project: Path):
    controller = Controller(load_settings(project))
    record = controller.run("fix small label", "safe", "mock", dry_run=False)
    assert record.status == "ready_for_review"
    report = ReportBuilder(controller.settings, controller).build(record.task_id)
    assert report.fields["Changed Files"]
    assert report.fields["Approval Status"] == "PENDING REVIEW"
    assert report.fields["Profile"] == NOT_RUN
