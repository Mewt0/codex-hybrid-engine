from __future__ import annotations

import time
from pathlib import Path
from .base import Provider, ProviderContext
from hybrid.tasks import TaskRecord, TaskResult


class MockPatchProvider(Provider):
    name = "mock"
    kind = "agent"

    def available(self) -> tuple[bool, str]:
        return True, "test provider"

    def execute(self, task: TaskRecord, context: ProviderContext) -> TaskResult:
        start = time.monotonic()
        target = context.project_dir / "app.js"
        if target.exists():
            target.write_text(target.read_text(encoding="utf-8").replace("BROKEN", "FIXED"), encoding="utf-8")
        return TaskResult(task.task_id, self.name, "ok", time.monotonic() - start, "mock change complete")

