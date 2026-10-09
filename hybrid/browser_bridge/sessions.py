from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json
import os
import tempfile
import time
import uuid

from .errors import BrowserBridgeError, ResponseAlreadyImported


@dataclass
class BrowserTask:
    """Local bookkeeping for one relayed web-chat task.

    Stores only task data and explicitly imported responses. Never credentials,
    cookies, tokens or browser profile data.
    """

    task_id: str
    provider: str
    description: str
    profile: str
    status: str
    task_mode: str = "browser"
    url: str = ""
    prompt_path: str = ""
    response_path: str | None = None
    review_path: str | None = None
    engine_task_id: str | None = None
    skills: list[str] = field(default_factory=list)
    response_sha256: str | None = None
    import_count: int = 0
    # Immutable audit trail of what was actually sent and where the answer came
    # from, so a prompt can never be silently swapped under a task id.
    prompt_sha256: str = ""
    prompt_source: str = ""
    conversation_url: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @staticmethod
    def new(provider: str, description: str, profile: str, url: str) -> "BrowserTask":
        return BrowserTask(
            task_id="BTASK-" + uuid.uuid4().hex[:8].upper(),
            provider=provider,
            description=description,
            profile=profile,
            status="WAITING_FOR_USER",
            url=url,
        )

    def to_dict(self) -> dict:
        return asdict(self)


class BrowserTaskStore:
    """Atomic JSON store rooted at <data_dir>/browser-tasks."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "browser-tasks"
        self.index_path = self.root / "index.json"

    # -- paths --------------------------------------------------------------

    def task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def prompt_file(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "prompt.md"

    def response_file(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "response.md"

    def review_file(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "review.json"

    def metadata_file(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "metadata.json"

    # -- index --------------------------------------------------------------

    def all(self) -> dict[str, dict]:
        if not self.index_path.exists():
            return {}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def save(self, task: BrowserTask) -> BrowserTask:
        task.updated_at = time.time()
        self.task_dir(task.task_id).mkdir(parents=True, exist_ok=True)
        data = self.all()
        data[task.task_id] = task.to_dict()
        self._write_atomic(self.metadata_file(task.task_id), json.dumps(task.to_dict(), indent=2, ensure_ascii=False) + "\n")
        self._write_atomic(self.index_path, json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        return task

    def get(self, task_id: str) -> BrowserTask:
        entry = self.all().get(task_id)
        if entry is None:
            raise BrowserBridgeError(f"Unknown browser task: {task_id}")
        return BrowserTask(**entry)

    def history(self) -> list[BrowserTask]:
        return sorted((BrowserTask(**entry) for entry in self.all().values()), key=lambda item: item.created_at)

    def cancel(self, task_id: str) -> BrowserTask:
        task = self.get(task_id)
        task.status = "CANCELLED"
        return self.save(task)

    # -- artifacts ----------------------------------------------------------

    def write_prompt(self, task_id: str, text: str) -> Path:
        path = self.prompt_file(task_id)
        self._write_atomic(path, text.replace("\r\n", "\n"))
        return path

    def read_prompt(self, task_id: str) -> str:
        path = self.prompt_file(task_id)
        if not path.exists():
            raise BrowserBridgeError(f"No prepared prompt for {task_id}; run `hybrid browser prepare` first")
        return path.read_text(encoding="utf-8")

    def import_response(self, task_id: str, text: str, force: bool = False) -> tuple[Path, str]:
        """Persist an imported response.

        A second import must be explicit (`force=True`); silently overwriting a
        response that already went through validation is refused.
        """
        task = self.get(task_id)
        # Hash exactly what gets stored: normalise line endings first so a CRLF
        # copy of the same answer counts as the same import.
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if task.response_sha256 and not force:
            if digest == task.response_sha256:
                raise ResponseAlreadyImported("Identical response was already imported for this task")
            raise ResponseAlreadyImported(
                "A response was already imported and validated for this task; pass --force to replace it"
            )
        path = self.response_file(task_id)
        self._write_atomic(path, normalized)
        task.response_path = str(path)
        task.response_sha256 = digest
        task.import_count += 1
        self.save(task)
        return path, digest

    def write_review(self, task_id: str, payload: dict) -> Path:
        path = self.review_file(task_id)
        self._write_atomic(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        task = self.get(task_id)
        task.review_path = str(path)
        self.save(task)
        return path

    def _write_atomic(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
