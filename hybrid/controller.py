from __future__ import annotations

from pathlib import Path
from fnmatch import fnmatch
import hashlib
import shutil
import subprocess
import tempfile
from .config import Settings
from .state import StateStore
from .tasks import TaskComplexity, TaskRecord, TaskStatus
from .providers.base import ProviderContext, ProviderError
from .providers.codex import CodexProvider
from .providers.groq import GroqProvider
from .providers.openrouter import OpenRouterProvider
from .providers.mock import MockPatchProvider
from .execution import worktree
from .quality.checks import validate_paths, run_quality, validate_dependencies


class Controller:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = StateStore(settings.state_file)

    def classify(self, description: str) -> TaskComplexity:
        text = description.lower()
        critical = ["auth", "авториза", "password", "парол", "payment", "security", "sql", "database", "бд"]
        hard = ["architecture", "архитект", "refactor", "рефактор", "game logic", "игров"]
        easy = ["css", "style", "doc", "docs", "documentation", "документ", "readme", "текст", "format", "цвет"]
        if any(w in text for w in critical):
            return TaskComplexity.CRITICAL
        if any(w in text for w in hard):
            return TaskComplexity.HARD
        if any(w in text for w in easy):
            return TaskComplexity.EASY
        if len(description) < 80:
            return TaskComplexity.MEDIUM
        return TaskComplexity.HARD

    def select_provider(self, complexity: TaskComplexity, forced: str | None) -> str:
        if forced:
            return forced
        if complexity in {TaskComplexity.EASY, TaskComplexity.TRIVIAL}:
            return "groq"
        return "codex"

    def plan(self, description: str, mode: str, forced_provider: str | None = None) -> TaskRecord:
        complexity = self.classify(description)
        provider = self.select_provider(complexity, forced_provider)
        return TaskRecord.new(description, mode, provider, complexity.value, self.settings.root)

    def run(self, description: str, mode: str, provider: str | None, dry_run: bool) -> TaskRecord:
        record = self.plan(description, mode, provider)
        record.artifact_dir = str(self._artifact_dir(record.task_id))
        if dry_run:
            record.status = TaskStatus.PLANNED.value
            record.checks = {
                "planned_checks": ["path validation", "git diff --check", "syntax checks when tools exist"],
                "context_files": [str(p.relative_to(self.settings.root)) for p in self._target_files(self.settings.root, cloud=record.provider == "groq")],
            }
            self.store.save(record)
            return record
        try:
            self._check_enabled(record.provider)
            worktree.ensure_repo(self.settings.root)
            self._ignore_internal_state()
            record.base_commit = worktree.base_commit(self.settings.root)
            record.base_ref = record.base_commit
            provider_obj = self._provider(record.provider)
            if provider_obj.kind == "agent":
                self._reject_project_symlinks(self.settings.root)
            if mode == "safe":
                exec_dir, branch = worktree.create_worktree(self.settings.root, record.task_id, self.settings.data_dir)
                record.worktree_dir = str(exec_dir)
                record.branch = branch
            elif provider_obj.kind == "agent":
                exec_dir = Path(tempfile.mkdtemp(prefix=f"{record.task_id}-", dir=self._artifact_dir(record.task_id)))
                self._copy_project(self.settings.root, exec_dir)
                record.worktree_dir = str(exec_dir)
            else:
                exec_dir = self.settings.root
            self.store.save(record)
            record.status = TaskStatus.RUNNING.value
            record.attempts += 1
            self.store.save(record)
            context_files = self._target_files(exec_dir, cloud=provider_obj.kind == "model")
            result = provider_obj.execute(
                record,
                ProviderContext(project_dir=exec_dir, settings=self.settings.raw, target_files=context_files),
            )
            if result.status != "ok":
                record.output = result.output
                record.error = result.error or f"Provider returned status: {result.status}"
                record.status = TaskStatus.FAILED.value
                self.store.save(record)
                return record
            record.output = result.output
            if provider_obj.kind == "model":
                if not result.output or not result.output.strip():
                    raise ProviderError("Provider returned no patch or output.")
                self._save_patch(record, result.output)
                checks = self._validate_patch_on_temp(record, result.output)
                record.checks = {c.name: {"status": c.status, "detail": c.detail} for c in checks}
                record.status = TaskStatus.READY_FOR_REVIEW.value if not self._has_fail(checks) else TaskStatus.FAILED.value
                self.store.save(record)
                return record
            record.changed_files = worktree.changed_files(exec_dir, include_ignored=True)
            diff_text = worktree.diff(exec_dir)
            if not diff_text.strip():
                raise ProviderError("Provider completed without producing file changes.")
            self._save_patch(record, diff_text)
            checks = validate_paths(exec_dir, record.changed_files, self.settings.raw["architecture"])
            if not self._has_fail(checks):
                checks.extend(validate_dependencies(exec_dir, record.changed_files, self.settings.raw["architecture"]))
                checks.extend(run_quality(exec_dir, record.changed_files))
            record.checks = {c.name: {"status": c.status, "detail": c.detail} for c in checks}
            record.status = TaskStatus.READY_FOR_REVIEW.value if not self._has_fail(checks) else TaskStatus.FAILED.value
        except Exception as exc:
            record.status = TaskStatus.FAILED.value
            record.error = str(exc)
        self.store.save(record)
        return record

    def _provider(self, name: str):
        self._check_enabled(name)
        if name == "codex":
            return CodexProvider(self.settings.raw["providers"]["codex"])
        if name == "groq":
            return GroqProvider(self.settings.raw["providers"]["groq"], self.settings.raw["budget"])
        if name == "openrouter":
            return OpenRouterProvider(self.settings.raw["providers"]["openrouter"], self.settings.raw["budget"])
        if name == "mock":
            return MockPatchProvider()
        raise ProviderError(f"Unknown provider: {name}")

    def _check_enabled(self, name: str) -> None:
        if self.settings.raw.get("providers", {}).get(name, {}).get("enabled", True) is not True:
            raise ProviderError(f"Provider {name} is disabled; no call was made.")

    def _target_files(self, root: Path, cloud: bool = False) -> list[Path]:
        root = root.resolve()
        forbidden = self.settings.raw["architecture"].get("forbidden_paths", [])
        secret_names = {".env", ".env.local", "secrets.json", "credentials.json"}
        secret_markers = ["secret", "token", "credential", "password", "private"]
        files = []
        allowed = self.settings.raw.get("context", {}).get("allowed_files", [])
        total = 0
        for path in sorted(root.rglob("*")):
            if len(files) >= 8 or sum(p.stat().st_size for p in files if p.exists()) > 80_000:
                break
            if not path.is_file() or path.suffix not in {".php", ".js", ".css", ".md", ".json", ".py"}:
                continue
            rel = path.relative_to(root).as_posix()
            if self._is_sensitive_relpath(rel, path) or path.is_symlink():
                continue
            if cloud and rel not in allowed:
                continue
            if any(part in {".git", ".hybrid", "__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            if path.name in secret_names or any(marker in rel.lower() for marker in secret_markers):
                continue
            if any(fnmatch(rel, pattern) for pattern in forbidden):
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            size = path.stat().st_size
            if size + total > 80_000:
                continue
            files.append(path)
            total += size
        return files

    def _artifact_dir(self, task_id: str) -> Path:
        path = self.settings.data_dir / "tasks" / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _save_patch(self, record: TaskRecord, patch: str) -> Path:
        path = self._artifact_dir(record.task_id) / "proposed.patch"
        # Patches must stay LF-only: a CRLF patch is rejected by `git apply
        # --cached` (and by the temp-repo validation below) on Windows.
        normalized = patch.replace("\r\n", "\n")
        path.write_text(normalized, encoding="utf-8", newline="\n")
        record.patch_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return path

    def _patch_path(self, record: TaskRecord) -> Path:
        return self._artifact_dir(record.task_id) / "proposed.patch"

    def _copy_project(self, src: Path, dst: Path) -> None:
        ignore = self._copy_ignore
        shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=False, ignore=ignore)
        subprocess.run(["git", "init"], cwd=dst, text=True, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "hybrid@example.invalid"], cwd=dst, check=True)
        subprocess.run(["git", "config", "user.name", "Codex Hybrid Engine"], cwd=dst, check=True)
        subprocess.run(["git", "add", "."], cwd=dst, check=True)
        subprocess.run(["git", "commit", "-m", "Temporary baseline"], cwd=dst, text=True, capture_output=True, check=True)

    def _copy_ignore(self, directory: str, names: list[str]) -> set[str]:
        ignored = {".hybrid", ".git", "__pycache__", ".pytest_cache"}
        root = self.settings.root.resolve()
        current = Path(directory).resolve()
        for name in names:
            path = current / name
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = name
            if self._is_sensitive_relpath(rel, Path(name)):
                ignored.add(name)
        return ignored

    def _is_sensitive_relpath(self, rel: str, path: Path) -> bool:
        forbidden = self.settings.raw["architecture"].get("forbidden_paths", [])
        secret_names = {".env", ".env.local", "secrets.json", "credentials.json"}
        secret_markers = ["secret", "token", "credential", "password", "private"]
        return (
            path.name in secret_names
            or any(part.lower() in {"config", "configs", "configuration", "sessions", ".git", ".hybrid"} for part in Path(rel).parts)
            or path.name.lower().startswith(".env")
            or any(marker in rel.lower() for marker in secret_markers)
            or any(fnmatch(rel, pattern) for pattern in forbidden)
        )

    def _reject_project_symlinks(self, root: Path) -> None:
        for path in root.rglob("*"):
            if any(part in {".git", ".hybrid", "__pycache__", ".pytest_cache"} for part in path.parts):
                continue
            if path.is_symlink():
                raise ProviderError(f"Project contains symlink; refusing agent execution: {path.relative_to(root).as_posix()}")

    def _validate_patch_on_temp(self, record: TaskRecord, patch: str):
        from .quality.checks import CheckResult

        temp_dir = Path(tempfile.mkdtemp(prefix=f"{record.task_id}-patch-", dir=self._artifact_dir(record.task_id)))
        self._copy_project(self.settings.root, temp_dir)
        # A patch carries blob ids of the real project HEAD. The temp copy is a
        # committed snapshot with its own history, so pull the project objects
        # in and reset to the recorded HEAD before comparing blobs.
        if record.base_ref:
            try:
                worktree.fetch_from(self.settings.root, temp_dir, record.base_ref)
            except Exception as exc:
                return [CheckResult("Patch Validation", "FAIL", f"Could not prepare the validation copy: {exc}")]
        patch_file = self._artifact_dir(record.task_id) / "model.patch"
        patch_file.write_text(patch.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
        proc = subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=temp_dir, text=True, capture_output=True)
        if proc.returncode != 0:
            return [CheckResult("Patch Validation", "FAIL", (proc.stdout + proc.stderr).strip()[-2000:])]
        try:
            affected = worktree.affected_paths_from_patch(temp_dir, patch_file)
        except Exception as exc:
            return [CheckResult("Patch Paths", "FAIL", f"Could not determine affected paths: {exc}")]
        path_results = validate_paths(temp_dir, affected, self.settings.raw["architecture"])
        if self._has_fail(path_results):
            record.changed_files = affected
            return [CheckResult("Patch Validation", "PASS", "patch applies cleanly"), *path_results]
        subprocess.run(["git", "apply", str(patch_file)], cwd=temp_dir, check=True)
        worktree.prepare_paths_for_diff(temp_dir, affected)
        changed = worktree.changed_files(temp_dir, include_ignored=True)
        changed = sorted(set(changed).union(affected))
        record.changed_files = changed
        results = [CheckResult("Patch Validation", "PASS", "patch applies cleanly")]
        if patch.strip() and not changed:
            results.append(CheckResult("Patch Paths", "FAIL", "non-empty patch produced no detectable changed files"))
        else:
            results.append(CheckResult("Patch Paths", "PASS", ", ".join(changed)))
        results.extend(validate_paths(temp_dir, changed, self.settings.raw["architecture"]))
        if not self._has_fail(results):
            results.extend(validate_dependencies(temp_dir, changed, self.settings.raw["architecture"]))
            results.extend(run_quality(temp_dir, changed))
        return results

    def _ignore_internal_state(self) -> None:
        git_dir = self.settings.root / ".git"
        exclude = git_dir / "info" / "exclude"
        if not exclude.exists():
            return
        text = exclude.read_text(encoding="utf-8")
        if ".hybrid/" not in text:
            exclude.write_text(text.rstrip() + "\n.hybrid/\n", encoding="utf-8")

    def _files_from_patch(self, patch: str) -> list[str]:
        raise ProviderError("Patch paths are determined by git apply --numstat, not by textual diff headers.")

    def _has_fail(self, checks) -> bool:
        return any(c.status == "FAIL" for c in checks)

    def status(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def diff(self, task_id: str) -> str:
        record = self.store.get(task_id)
        patch = self._patch_path(record)
        if patch.exists():
            return patch.read_text(encoding="utf-8")
        return worktree.diff(Path(record.worktree_dir or record.project_dir))

    def apply(self, task_id: str, confirm: bool = False) -> TaskRecord:
        record = self.store.get(task_id)
        if not confirm:
            raise RuntimeError("Explicit confirmation is required. Use CLI: hybrid apply TASK --yes")
        if record.approved or record.status == TaskStatus.APPLIED.value:
            raise RuntimeError("Task has already been applied")
        if record.status != TaskStatus.READY_FOR_REVIEW.value:
            raise RuntimeError(f"Task is not ready for review: {record.status}")
        if record.base_commit and worktree.base_commit(Path(record.project_dir)) != record.base_commit:
            raise RuntimeError("Project HEAD changed after review; re-run the task before applying.")
        if not worktree.is_clean(Path(record.project_dir)):
            raise RuntimeError("Project has local changes; refusing to apply over user work.")
        patch_file = self._patch_path(record)
        if not patch_file.exists():
            raise RuntimeError("Task patch artifact is missing")
        diff_text = patch_file.read_text(encoding="utf-8")
        if hashlib.sha256(diff_text.encode("utf-8")).hexdigest() != record.patch_sha256:
            raise RuntimeError("Patch artifact changed after review")
        # Re-apply the exact artifact in a disposable repository. Git, not patch
        # header heuristics, determines deletions and both sides of renames.
        checks = self._validate_patch_on_temp(record, diff_text)
        if self._has_fail(checks):
            raise RuntimeError("Quality validation failed before apply")
        changed = record.changed_files
        checks = validate_paths(Path(record.project_dir), changed, self.settings.raw["architecture"])
        if self._has_fail(checks):
            raise RuntimeError("Path validation failed before apply")
        if not diff_text.strip():
            raise RuntimeError("No changes to apply")
        subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=Path(record.project_dir), check=True)
        subprocess.run(["git", "apply", str(patch_file)], cwd=Path(record.project_dir), check=True)
        record.approved = True
        record.status = TaskStatus.APPLIED.value
        self.store.save(record)
        return record

