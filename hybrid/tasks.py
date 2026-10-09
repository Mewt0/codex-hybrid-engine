from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
import dataclasses
import time
import uuid


class TaskStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    READY_FOR_REVIEW = "ready_for_review"
    APPLIED = "applied"
    FAILED = "failed"


class TaskComplexity(StrEnum):
    TRIVIAL = "trivial"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    CRITICAL = "critical"


@dataclass
class TaskResult:
    task_id: str
    provider: str
    status: str
    duration_seconds: float
    output: str | None = None
    error: str | None = None


@dataclass
class TaskRecord:
    task_id: str
    description: str
    mode: str
    provider: str
    complexity: str
    status: str = TaskStatus.PLANNED.value
    attempts: int = 0
    approved: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    project_dir: str = ""
    worktree_dir: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    artifact_dir: str | None = None
    patch_sha256: str | None = None
    base_ref: str | None = None
    changed_files: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    output: str | None = None
    # Browser AI Bridge fields (web chat providers that need a human relay).
    profile: str | None = None
    source: str | None = None
    prompt_path: str | None = None
    response_path: str | None = None
    response_sha256: str | None = None
    import_count: int = 0
    analysis: str | None = None
    skills: list[str] = field(default_factory=list)

    @staticmethod
    def new(description: str, mode: str, provider: str, complexity: str, project_dir: Path) -> "TaskRecord":
        task_id = "TASK-" + uuid.uuid4().hex[:8].upper()
        return TaskRecord(
            task_id=task_id,
            description=description,
            mode=mode,
            provider=provider,
            complexity=complexity,
            project_dir=str(project_dir),
        )

    def to_dict(self) -> dict[str, Any]:
        data = self.__dict__.copy()
        data["updated_at"] = time.time()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        # Tolerate state written by older versions: keep only known fields so an
        # extra key can never break loading of previously saved tasks.
        known = {field.name for field in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

