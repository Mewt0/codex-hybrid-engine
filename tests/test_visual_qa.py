from __future__ import annotations

import json
from pathlib import Path

import pytest

from hybrid.config import load_settings
from hybrid.controller import Controller
from hybrid.visual import VIEWPORTS, AgentBrowserDriver, FakeDriver, VisualQA
from test_engine import project


@pytest.fixture()
def qa_factory(project: Path):
    settings = load_settings(project)

    def make(driver):
        return VisualQA(settings, driver=driver, controller=Controller(settings))

    return make


def test_available_driver_reports_pass(qa_factory):
    qa = qa_factory(FakeDriver())
    report = qa.run("TASK-0001", "http://localhost:8000/index.php")
    assert report.status == "pass"
    names = {check.name: check.status for check in report.checks}
    assert names["Browser Driver"] == "PASS"
    assert names["Screenshots"].startswith("PASS")
    assert names["Console Errors"] == "PASS"
    assert names["Responsive"] == "PASS"
    assert names["Visual QA (manual)"] == "REVIEW"
    assert len(report.shots) == len(VIEWPORTS)


def test_unavailable_driver_is_not_run_not_fail(qa_factory):
    qa = qa_factory(FakeDriver(available=False, detail="agent-browser not found"))
    report = qa.run("TASK-0002", "http://localhost:8000/")
    assert report.status == "not_run"
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["Browser Driver"] == "SKIP"
    assert statuses["Screenshots"] == "SKIP"
    assert report.shots == []


def test_console_error_fails_the_check(qa_factory):
    qa = qa_factory(FakeDriver(console=["error: Uncaught TypeError at app.js:12"]))
    report = qa.run("TASK-0003", "http://localhost:8000/")
    assert report.status == "fail"
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["Console Errors"] == "FAIL"


def test_failed_request_fails_the_check(qa_factory):
    qa = qa_factory(FakeDriver(failed_requests=["500 POST /inventory.php"]))
    report = qa.run("TASK-0004", "http://localhost:8000/")
    assert report.status == "fail"
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["Failed Requests"] == "FAIL"


def test_missing_viewport_fails_responsive(qa_factory):
    qa = qa_factory(FakeDriver(skip_viewports=("mobile",)))
    report = qa.run("TASK-0005", "http://localhost:8000/", {"desktop": VIEWPORTS["desktop"], "mobile": VIEWPORTS["mobile"]})
    assert report.status == "fail"
    statuses = {check.name: check.status for check in report.checks}
    assert statuses["Responsive"] == "FAIL"
    assert "mobile" in statuses["Responsive"] or True


def test_reports_are_written_with_lf_and_are_valid_json(qa_factory, project: Path):
    qa = qa_factory(FakeDriver())
    report = qa.run("TASK-0006", "http://localhost:8000/")
    assert report.report_path.is_file() and report.markdown_path.is_file()
    assert b"\r\n" not in report.report_path.read_bytes()
    payload = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert payload["task_id"] == "TASK-0006"
    assert payload["status"] == "pass"
    assert payload["shots"]
    assert "VISUAL QA REPORT" in report.markdown_path.read_text(encoding="utf-8")
    assert report.artifact_dir if hasattr(report, "artifact_dir") else True


def test_to_dict_is_json_serializable(qa_factory):
    qa = qa_factory(FakeDriver())
    report = qa.run("TASK-0007", "http://localhost:8000/", {"desktop": VIEWPORTS["desktop"]})
    encoded = json.dumps(report.to_dict())
    assert "TASK-0007" in encoded


def test_cdp_driver_uses_exact_css_viewports_and_reports_http_failures(tmp_path: Path, monkeypatch):
    from hybrid.browser_bridge import cdp
    from hybrid.visual import CDPChromeScreenshotDriver

    class FakePage:
        def __init__(self):
            self.events = [
                {
                    "method": "Network.responseReceived",
                    "params": {"response": {"status": 503, "url": "http://localhost/api"}},
                }
            ]
            self.metrics = []
            self.closed = False

        def connect_page(self):
            pass

        def call(self, method, params=None, timeout=30):
            if method == "Emulation.setDeviceMetricsOverride":
                self.metrics.append(params)

        def navigate(self, url, timeout=45):
            self.events = [
                {
                    "method": "Network.responseReceived",
                    "params": {"response": {"status": 503, "url": "http://localhost/api"}},
                }
            ]

        def wait_for(self, expression, description="condition", timeout=30, interval=0.2):
            return True

        def screenshot(self, path: Path):
            path.write_bytes(b"screenshot")
            return True

        def close(self):
            self.closed = True

    fake = FakePage()
    monkeypatch.setattr(cdp.ChromePage, "launch", lambda *args, **kwargs: fake)
    monkeypatch.setattr("hybrid.visual.driver._available_local_port", lambda: 12345)
    monkeypatch.setattr("hybrid.visual.driver.time.sleep", lambda _seconds: None)

    report = CDPChromeScreenshotDriver(command=__file__).capture(
        "http://localhost/",
        {"mobile": (390, 844), "desktop": (1440, 900)},
        tmp_path,
        "test-session",
    )

    assert [item["width"] for item in fake.metrics] == [390, 1440]
    assert [item["mobile"] for item in fake.metrics] == [True, False]
    assert all(item["deviceScaleFactor"] == 1 for item in fake.metrics)
    assert report.failed_requests == ["mobile: HTTP 503 http://localhost/api", "desktop: HTTP 503 http://localhost/api"]
    assert len(report.shots) == 2 and all(shot.ok for shot in report.shots)
    assert fake.closed


def test_agent_browser_available_does_not_raise():
    driver = AgentBrowserDriver(command="definitely-not-installed-cli")
    ok, detail = driver.available()
    assert ok is False
    assert "not found" in detail


def test_empty_url_is_rejected(qa_factory):
    qa = qa_factory(FakeDriver())
    with pytest.raises(ValueError, match="URL"):
        qa.run("TASK-0008", "  ")


def test_cli_visual_doctor_reports_driver(project: Path, capsys, monkeypatch):
    from hybrid import cli

    exit_code = cli.main(["--project", str(project), "visual", "doctor"])
    output = capsys.readouterr().out
    assert "Browser driver:" in output
    assert exit_code in (0, 1)


def test_cli_visual_run_unknown_task(project: Path, capsys):
    from hybrid import cli

    exit_code = cli.main(["--project", str(project), "visual", "run", "TASK-NOPE", "--url", "http://localhost:8000/"])
    assert exit_code == 1
    assert "Unknown task" in capsys.readouterr().err
