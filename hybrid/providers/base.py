from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from hybrid.tasks import TaskRecord, TaskResult


@dataclass
class ProviderContext:
    project_dir: Path
    settings: dict
    target_files: list[Path]


class ProviderError(RuntimeError):
    pass


class Provider:
    name = "base"
    kind = "model"

    def available(self) -> tuple[bool, str]:
        return False, "not implemented"

    def execute(self, task: TaskRecord, context: ProviderContext) -> TaskResult:
        raise NotImplementedError

