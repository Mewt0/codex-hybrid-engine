from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import time

from hybrid.tasks import TaskRecord

# The canonical report shape requested by the master plan. Extra keys are
# allowed, missing keys are not: an unexecuted check must appear as NOT RUN
# rather than disappearing from the report.
REPORT_FIELDS = (
    "Task",
    "Provider",
    "Model",
    "Profile",
    "Skills Used",
    "Changed Files",
    "PHP Checks",
    "JavaScript Checks",
    "SQL Checks",
    "Functional Tests",
    "Browser QA",
    "Responsive QA",
    "Screenshots",
    "Warnings",
    "Errors",
    "Approval Status",
)

NOT_RUN = "NOT RUN"


@dataclass
class TaskReport:
    task_id: str
    fields: dict[str, Any]
    checks: dict[str, Any] = field(default_factory=dict)
    generated_at: float = field(default_factory=time.time)
    json_path: Path | None = None
    markdown_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "generated_at": self.generated_at,
            "fields": self.fields,
            "checks": self.checks,
            "json_path": str(self.json_path) if self.json_path else None,
            "markdown_path": str(self.markdown_path) if self.markdown_path else None,
        }

    def render_markdown(self) -> str:
        lines = ["# TASK RESULT", ""]
        for name in REPORT_FIELDS:
            lines.append(f"**{name}:** {self._render(self.fields.get(name, NOT_RUN))}")
            lines.append("")
        if self.checks:
            lines.append("## Checks")
            lines.append("")
            for name, value in sorted(self.checks.items()):
                status, detail = _check_parts(value)
                if detail:
                    lines.append(f"- {name}: {status} — {detail}")
                else:
                    lines.append(f"- {name}: {status}")
            lines.append("")
        return "\n".join(lines).rstrip("\n") + "\n"

    def _render(self, value: Any) -> str:
        if value in (None, "", [], {}):
            return NOT_RUN
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value) if value else NOT_RUN
        return str(value)


class ReportBuilder:
    """Builds the review report for one task from durable state only."""

    def __init__(self, settings, controller):
        self.settings = settings
        self.controller = controller

    def build(self, task_id: str) -> TaskReport:
        record = self._record(task_id)
        checks = self._normalized_checks(record)
        visual = self._visual_results(record)
        fields = {
            "Task": record.task_id,
            "Provider": record.provider,
            "Model": self._model(record),
            "Profile": record.profile or self._profile_from_checks(record),
            "Skills Used": list(record.skills or []),
            "Changed Files": list(record.changed_files or []),
            "PHP Checks": self._pick(checks, ("php", "PHP")),
            "JavaScript Checks": self._pick(checks, ("js", "javascript", "JavaScript")),
            "SQL Checks": self._pick(checks, ("sql", "SQL")),
            "Functional Tests": self._pick(checks, ("behavior", "test", "functional")),
            "Browser QA": visual.get("console") or visual.get("webdriver") or NOT_RUN,
            "Responsive QA": visual.get("responsive", NOT_RUN),
            "Screenshots": visual.get("screenshots", []),
            "Warnings": [detail for value in checks.values() for status, detail in [_check_parts(value)] if status == "WARN"],
            "Errors": self._errors(record, checks),
            "Approval Status": self._approval(record),
        }
        report = TaskReport(task_id=record.task_id, fields=fields, checks=checks)
        self._write(report, record)
        return report

    # -- internals ----------------------------------------------------------

    def _record(self, task_id: str) -> TaskRecord:
        try:
            return self.controller.store.get(task_id)
        except KeyError as exc:
            raise KeyError(f"Unknown task: {task_id}") from exc

    def _write(self, report: TaskReport, record: TaskRecord) -> None:
        artifact_dir = self.controller._artifact_dir(record.task_id)
        json_path = artifact_dir / "report.json"
        markdown_path = artifact_dir / "report.md"
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        markdown_path.write_text(report.render_markdown(), encoding="utf-8", newline="\n")
        report.json_path = json_path
        report.markdown_path = markdown_path

    def _normalized_checks(self, record: TaskRecord) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        raw = record.checks or {}
        if isinstance(raw, dict):
            for name, value in raw.items():
                status, detail = _check_parts(value)
                checks[name] = {"status": status, "detail": detail}
        elif isinstance(raw, list):
            for value in raw:
                status, detail = _check_parts(value)
                name = getattr(value, "name", "Check")
                checks[name] = {"status": status, "detail": detail}
        return checks

    def _pick(self, checks: dict[str, Any], markers: tuple[str, ...]) -> str:
        found = []
        for name, value in checks.items():
            if any(marker.lower() in name.lower() for marker in markers):
                status, _ = _check_parts(value)
                found.append(f"{name}: {status}")
        return "; ".join(found) if found else NOT_RUN

    def _errors(self, record: TaskRecord, checks: dict[str, Any]) -> list[str]:
        errors = [record.error] if record.error else []
        errors.extend(
            f"{name}: {detail}"
            for name, value in sorted(checks.items())
            for status, detail in [_check_parts(value)]
            if status == "FAIL"
        )
        return errors

    def _approval(self, record: TaskRecord) -> str:
        if record.status == "applied":
            return "APPLIED (confirmed by user)"
        if record.approved:
            return "APPROVED"
        if record.status == "ready_for_review":
            return "PENDING REVIEW"
        if record.status in {"waiting_for_user", "planned"}:
            return "NOT SUBMITTED"
        return record.status.upper()

    def _model(self, record: TaskRecord) -> str:
        provider = str(record.provider)
        config = self.settings.raw.get("providers", {}).get(provider, {})
        if isinstance(config, dict):
            for key in ("small_model", "review_model", "model"):
                if config.get(key):
                    return str(config[key])
        return NOT_RUN

    def _profile_from_checks(self, record: TaskRecord) -> str:
        source = str(record.source or "")
        if source == "browser_bridge":
            return "browser (profile recorded on the browser task)"
        return NOT_RUN

    def _visual_results(self, record: TaskRecord) -> dict[str, Any]:
        artifact_dir = self.controller._artifact_dir(record.task_id)
        visual_dir = artifact_dir / "visual"
        report_path = visual_dir / "report.json"
        result: dict[str, Any] = {}
        if report_path.is_file():
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
            for check in payload.get("checks", []):
                name = str(check.get("name", ""))
                status = check.get("status", NOT_RUN)
                if name == "Console Errors":
                    result["console"] = f"{status}" + (f" ({check.get('detail')})" if check.get("detail") else "")
                elif name == "Responsive":
                    result["responsive"] = f"{status}" + (f" ({check.get('detail')})" if check.get("detail") else "")
                elif name == "Browser Driver":
                    result["webdriver"] = f"{status}" + (f" ({check.get('detail')})" if check.get("detail") else "")
            shots = sorted(path.name for path in visual_dir.glob("*.png"))
            if shots:
                result["screenshots"] = [str(visual_dir / name) for name in shots]
        return result


def _check_parts(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        return str(value.get("status", NOT_RUN)), str(value.get("detail", "") or "")
    status = getattr(value, "status", None)
    if status is not None:
        return str(status), str(getattr(value, "detail", "") or "")
    return str(value), ""
