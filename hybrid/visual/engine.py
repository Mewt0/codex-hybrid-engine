from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import time
import uuid

from hybrid.quality.checks import CheckResult
from .driver import AgentBrowserDriver, BrowserDriver, CDPChromeScreenshotDriver, DriverResult, Shot, find_chrome

VIEWPORTS: dict[str, tuple[int, int]] = {
    "mobile": (390, 844),
    "tablet": (768, 1024),
    "desktop": (1440, 900),
}

CONSOLE_ERRORS = "Console Errors"
FAILED_REQUESTS = "Failed Requests"
RESPONSIVE = "Responsive"
SCREENSHOTS = "Screenshots"
DRIVER = "Browser Driver"
MANUAL_REVIEW = "Visual QA (manual)"


@dataclass
class VisualReport:
    task_id: str
    url: str
    status: str
    checks: list[CheckResult] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)
    report_path: Path | None = None
    markdown_path: Path | None = None
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "status": self.status,
            "generated_at": self.generated_at,
            "checks": [{"name": check.name, "status": check.status, "detail": check.detail} for check in self.checks],
            "shots": [
                {"viewport": shot.viewport, "path": str(shot.path), "url": shot.url, "ok": shot.ok, "detail": shot.detail}
                for shot in self.shots
            ],
            "report_path": str(self.report_path) if self.report_path else None,
            "markdown_path": str(self.markdown_path) if self.markdown_path else None,
        }

    def render_markdown(self) -> str:
        lines = [
            "# VISUAL QA REPORT",
            "",
            f"**Task:** {self.task_id}",
            f"**URL:** {self.url}",
            f"**Status:** {self.status}",
            "",
            "## Checks",
            "",
        ]
        for check in self.checks:
            detail = f" — {check.detail}" if check.detail else ""
            lines.append(f"- {check.name}: {check.status}{detail}")
        lines += ["", "## Screenshots", ""]
        if self.shots:
            for shot in self.shots:
                state = "ok" if shot.ok else f"FAILED ({shot.detail})"
                lines.append(f"- {shot.viewport} ({VIEWPORTS.get(shot.viewport, ('?', '?'))[0]}x{VIEWPORTS.get(shot.viewport, ('?', '?'))[1]}): `{Path(shot.path).name}` — {state}")
        else:
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)


class VisualQA:
    """Runs the visual check for one task and stores the evidence.

    A check that could not run is reported as NOT RUN / SKIP, never as PASS.
    """

    def __init__(self, settings, driver: BrowserDriver | None = None, controller=None):
        self.settings = settings
        self.controller = controller
        visual_config = settings.raw.get("visual", {})
        self.driver = driver or self._default_driver(visual_config)
        self.data_dir = Path(settings.data_dir)

    @staticmethod
    def _default_driver(visual_config: dict) -> BrowserDriver:
        """Prefer the direct headless Chrome driver; fall back to agent-browser."""
        timeout = int(visual_config.get("timeout_seconds", 60))
        configured = visual_config.get("command")
        if configured:
            return CDPChromeScreenshotDriver(command=configured, timeout_seconds=timeout)
        if find_chrome():
            return CDPChromeScreenshotDriver(timeout_seconds=timeout)
        return AgentBrowserDriver(
            command=visual_config.get("agent_browser_command", "agent-browser"),
            timeout_seconds=timeout,
        )

    def available(self) -> tuple[bool, str]:
        return self.driver.available()

    def artifact_dir(self, task_id: str) -> Path:
        return self.data_dir / "tasks" / task_id / "visual"

    def run(
        self,
        task_id: str,
        url: str,
        viewports: dict[str, tuple[int, int]] | None = None,
    ) -> VisualReport:
        if not url or not str(url).strip():
            raise ValueError("A URL is required for a visual check")
        selected = dict(viewports or VIEWPORTS)
        out_dir = self.artifact_dir(task_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        session = f"hybrid-{uuid.uuid4().hex[:8]}"

        report = VisualReport(task_id=task_id, url=url, status="not_run")
        ok, detail = self.driver.available()
        if not ok:
            report.checks = [
                CheckResult(DRIVER, "SKIP", detail),
                CheckResult(SCREENSHOTS, "SKIP", "no browser driver available"),
                CheckResult(CONSOLE_ERRORS, "SKIP", "no browser driver available"),
                CheckResult(FAILED_REQUESTS, "SKIP", "no browser driver available"),
                CheckResult(RESPONSIVE, "SKIP", "no browser driver available"),
                CheckResult(MANUAL_REVIEW, "REVIEW", "human judgement required"),
            ]
            return self._write(report)

        results: DriverResult = self.driver.capture(url, selected, out_dir, session, log_dir=out_dir / "logs")
        report.shots = results.shots
        captured = [shot for shot in results.shots if shot.ok]

        checks = [CheckResult(DRIVER, "PASS" if results.ok else "FAIL", results.detail or detail)]
        missing = [name for name in selected if name not in {shot.viewport for shot in captured}]
        checks.append(
            CheckResult(
                SCREENSHOTS,
                "PASS" if not missing else "FAIL",
                f"{len(captured)}/{len(selected)} captured" + (f"; missing: {', '.join(missing)}" if missing else ""),
            )
        )
        checks.append(
            CheckResult(
                CONSOLE_ERRORS,
                "FAIL" if results.console else "PASS",
                "; ".join(results.console[:5]) if results.console else "no console errors",
            )
        )
        checks.append(
            CheckResult(
                FAILED_REQUESTS,
                "FAIL" if results.failed_requests else "PASS",
                "; ".join(results.failed_requests[:5]) if results.failed_requests else "no failed requests",
            )
        )
        checks.append(
            CheckResult(RESPONSIVE, "PASS" if not missing else "FAIL", "all viewports captured" if not missing else f"missing: {', '.join(missing)}")
        )
        checks.append(CheckResult(MANUAL_REVIEW, "REVIEW", "human judgement required for visual quality"))

        has_fail = any(check.status == "FAIL" for check in checks)
        report.checks = checks
        report.status = "fail" if has_fail else "pass"
        return self._write(report)

    def _write(self, report: VisualReport) -> VisualReport:
        out_dir = self.artifact_dir(report.task_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        report.report_path = out_dir / "report.json"
        report.markdown_path = out_dir / "report.md"
        report.report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        report.markdown_path.write_text(report.render_markdown(), encoding="utf-8", newline="\n")
        return report
