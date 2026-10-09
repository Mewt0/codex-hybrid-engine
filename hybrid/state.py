from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import json
import os
import tempfile
from .tasks import TaskRecord


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> dict:
        if not self.path.exists():
            return {"tasks": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_all(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as lock:
            try:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(lock, fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass

    def save(self, record: TaskRecord) -> None:
        with self._locked():
            data = self._load_all()
            data.setdefault("tasks", {})[record.task_id] = record.to_dict()
            self._write_all(data)

    def get(self, task_id: str) -> TaskRecord:
        data = self._load_all()
        try:
            return TaskRecord.from_dict(data["tasks"][task_id])
        except KeyError as exc:
            raise KeyError(f"Unknown task: {task_id}") from exc

    def list(self) -> list[TaskRecord]:
        return [TaskRecord.from_dict(v) for v in self._load_all().get("tasks", {}).values()]

