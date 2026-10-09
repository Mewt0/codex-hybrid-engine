from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import shutil
import difflib

from hybrid.providers.base import ProviderError
from hybrid.providers.codex import CodexProvider


ALLOWED_SANDBOXES = {"read-only", "workspace-write"}


@dataclass
class CodexCliDelegateResult:
    status: str
    command: list[str]
    output: str = ""
    error: str | None = None
    output_path: Path | None = None
    returncode: int | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "command": self.command,
            "output": self.output,
            "error": self.error,
            "output_path": str(self.output_path) if self.output_path else None,
            "returncode": self.returncode,
            "duration_seconds": round(self.duration_seconds, 3),
        }


class CodexCliDelegate:
    """Controlled Codex CLI bridge for DeepSeek Harness subagents."""

    def __init__(self, codex_config: dict):
        self.provider = CodexProvider(codex_config)
        self.config = codex_config

    def available(self) -> tuple[bool, str]:
        return self.provider.available()

    def run_task(
        self,
        description: str,
        cwd: Path,
        *,
        timeout: int | None = None,
        sandbox: str = "read-only",
        output_path: Path | None = None,
        preflight: bool = True,
    ) -> CodexCliDelegateResult:
        start = time.monotonic()
        if os.environ.get("HYBRID_INSIDE_AGENT") == "1":
            return CodexCliDelegateResult("error", [], error="recursive codex delegation is disabled")
        if sandbox not in ALLOWED_SANDBOXES:
            allowed = ", ".join(sorted(ALLOWED_SANDBOXES))
            return CodexCliDelegateResult("error", [], error=f"unsupported codex sandbox {sandbox!r}; allowed: {allowed}")

        try:
            command = self.provider._resolve_command()
        except ProviderError as exc:
            return CodexCliDelegateResult("unavailable", [], error=str(exc), duration_seconds=time.monotonic() - start)

        try:
            effective_timeout = int(timeout if timeout is not None else self.config.get("timeout_seconds", 300))
        except (TypeError, ValueError):
            return CodexCliDelegateResult("error", [], error="codex delegation timeout must be a positive integer")
        if effective_timeout <= 0:
            return CodexCliDelegateResult("error", [], error="codex delegation timeout must be a positive integer")
        if preflight and sandbox == "workspace-write":
            preflight_result = _run_sandbox_preflight(command, cwd, self.provider._safe_env(command))
            if preflight_result.returncode != 0:
                preflight_args = _sandbox_preflight_args(command)
                return CodexCliDelegateResult(
                    "error",
                    preflight_args,
                    error="codex workspace-write sandbox preflight failed; refusing delegation",
                    output=(preflight_result.stdout + preflight_result.stderr)[-8000:],
                    returncode=preflight_result.returncode,
                    duration_seconds=time.monotonic() - start,
                )
        output_path = (output_path or (cwd / ".hybrid" / "harness" / "codex-result.md")).resolve()
        work_dir = Path(cwd).resolve()
        codex_output_path = output_path
        temp_root: tempfile.TemporaryDirectory[str] | None = None
        git_worktree = False
        if sandbox == "workspace-write":
            temp_root = tempfile.TemporaryDirectory(prefix="hybrid-codex-")
            work_dir = Path(temp_root.name) / "project"
            try:
                is_git_repo = subprocess.run(
                    ["git", "-C", str(Path(cwd).resolve()), "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    check=False,
                ).returncode == 0
                if is_git_repo:
                    created = subprocess.run(
                        ["git", "-C", str(Path(cwd).resolve()), "worktree", "add", "--detach", "--force", str(work_dir), "HEAD"],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    if created.returncode != 0:
                        raise OSError(created.stderr.strip() or "could not create isolated git worktree")
                    git_worktree = True
                    shutil.copytree(
                        Path(cwd).resolve(), work_dir, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", ".hybrid"),
                    )
                else:
                    shutil.copytree(Path(cwd).resolve(), work_dir, ignore=shutil.ignore_patterns(".git", ".hybrid"))
            except OSError as exc:
                if git_worktree:
                    _remove_worktree(Path(cwd).resolve(), work_dir)
                temp_root.cleanup()
                return CodexCliDelegateResult(
                    "error", [], error=f"could not prepare isolated workspace: {exc}",
                    duration_seconds=time.monotonic() - start,
                )
            try:
                codex_output_path = work_dir / output_path.relative_to(Path(cwd).resolve())
            except ValueError:
                # Explicit output outside the project stays outside the copy.
                codex_output_path = output_path
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            codex_output_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if temp_root:
                if git_worktree:
                    _remove_worktree(Path(cwd).resolve(), work_dir)
                temp_root.cleanup()
            return CodexCliDelegateResult(
                "error", [], error=f"could not prepare output file: {exc}",
                duration_seconds=time.monotonic() - start,
            )
        prompt = _delegated_prompt(description)
        args = [
            command,
            "exec",
            "-C",
            str(work_dir),
            "--sandbox",
            sandbox,
            "-o",
            str(codex_output_path),
            "-",
        ]
        try:
            proc = subprocess.run(
                args,
                cwd=work_dir,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=effective_timeout,
                check=False,
                env=self.provider._safe_env(command),
            )
        except subprocess.TimeoutExpired:
            if temp_root:
                if git_worktree:
                    _remove_worktree(Path(cwd).resolve(), work_dir)
                temp_root.cleanup()
            return CodexCliDelegateResult(
                "error",
                args,
                error=f"codex delegation timed out after {effective_timeout}s",
                duration_seconds=time.monotonic() - start,
                output_path=output_path,
            )
        status = "ok" if proc.returncode == 0 else "error"
        patch_text = ""
        if temp_root and proc.returncode == 0:
            if git_worktree:
                diff = subprocess.run(
                    ["git", "-C", str(work_dir), "diff", "--binary", "HEAD"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                patch_text = diff.stdout if diff.returncode == 0 else ""
            else:
                patch_text = _directory_diff(Path(cwd).resolve(), work_dir, output_path)
        try:
            source_output = codex_output_path if codex_output_path.exists() else output_path
            output = source_output.read_text(encoding="utf-8") if source_output.exists() else proc.stdout[-8000:]
            if patch_text:
                output = f"{output}\n\n--- WORKSPACE PATCH ---\n{patch_text}"
            if (
                temp_root
                and source_output == codex_output_path
                and codex_output_path.exists()
                and codex_output_path != output_path
            ):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(codex_output_path, output_path)
            if temp_root and patch_text:
                output_path.write_text(f"{output}\n", encoding="utf-8", newline="\n")
        except OSError as exc:
            status = "error"
            output = proc.stdout[-8000:]
            proc.stderr += f"\nCould not read Codex output: {exc}"
        error = None if status == "ok" else proc.stderr[-4000:] or "codex did not complete successfully"
        if temp_root:
            if git_worktree:
                _remove_worktree(Path(cwd).resolve(), work_dir)
            temp_root.cleanup()
        return CodexCliDelegateResult(
            status,
            args,
            output=output,
            error=error,
            output_path=output_path,
            returncode=proc.returncode,
            duration_seconds=time.monotonic() - start,
        )


def _delegated_prompt(description: str) -> str:
    return (
        "You are Codex CLI receiving delegated work from DeepSeek Harness.\n"
        "Follow the repository instructions and AGENTS.md. Do not commit or push.\n"
        "Report the exact checks you ran, and say NOT RUN for checks you did not run.\n"
        "If the sandbox is read-only, analyze only and do not attempt edits.\n\n"
        "Delegated task:\n"
        f"{description.strip()}\n"
    )


def _run_sandbox_preflight(command: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    args = _sandbox_preflight_args(command)
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=30,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args, 124, "", f"Codex sandbox preflight timed out: {exc}"
        )


def _sandbox_preflight_args(command: str) -> list[str]:
    if os.name == "nt":
        return [command, "sandbox", "windows", "cmd", "/c", "exit", "0"]
    return [command, "sandbox", "exec", "true"]


def _remove_worktree(repository: Path, worktree: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repository), "worktree", "remove", "--force", str(worktree)],
        capture_output=True,
        check=False,
    )


def _directory_diff(original: Path, modified: Path, excluded: Path) -> str:
    """Return a unified patch for changed project files, excluding artifacts."""
    excluded = excluded.resolve()
    chunks: list[str] = []
    original_paths: set[Path] = set()
    modified_paths: set[Path] = set()
    for base, collected in ((original, original_paths), (modified, modified_paths)):
        for path in base.rglob("*"):
            if not path.is_file() or ".git" in path.parts or ".hybrid" in path.parts or path.name == "capture.json":
                continue
            try:
                path.resolve().relative_to(excluded)
                continue
            except ValueError:
                pass
            relative = path.relative_to(base)
            collected.add(relative)
    paths = original_paths | modified_paths
    for relative in sorted(paths):
        old_path = original / relative
        new_path = modified / relative
        try:
            old = old_path.read_text(encoding="utf-8").splitlines(keepends=True) if old_path.exists() else []
            new = new_path.read_text(encoding="utf-8").splitlines(keepends=True) if new_path.exists() else []
        except (OSError, UnicodeError):
            continue
        chunks.extend(
            difflib.unified_diff(old, new, fromfile=f"a/{relative}", tofile=f"b/{relative}")
        )
    return "".join(chunks)


def result_json(result: CodexCliDelegateResult) -> str:
    return json.dumps(result.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
