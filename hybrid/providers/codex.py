from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import time
from .base import Provider, ProviderContext, ProviderError
from hybrid.tasks import TaskRecord, TaskResult


class CodexProvider(Provider):
    name = "codex"
    kind = "agent"

    # Variables a process needs to function, and which are not secrets.
    #
    # The Windows entries are not cosmetic: a process started without
    # `SystemRoot`/`windir` cannot initialise its network stack, and Codex then
    # fails every request with "Reconnecting... 5/5 / workspace routing
    # discovery failed" instead of reporting a usable error. `APPDATA` /
    # `LOCALAPPDATA` / `TEMP` are paths Codex uses for its own cache.
    ENV_ALLOWED = (
        "HOME",
        "LANG",
        "LC_ALL",
        "TERM",
        "TMPDIR",
        "USER",
        "USERNAME",
        "SHELL",
        "CODENEX_SANDBOX",
        "SystemRoot",
        "windir",
        "SystemDrive",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "OS",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "APPDATA",
        "LOCALAPPDATA",
        "ProgramData",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "TEMP",
        "TMP",
    )

    def __init__(self, config: dict):
        self.config = config

    def available(self) -> tuple[bool, str]:
        try:
            self._resolve_command()
        except ProviderError as exc:
            return False, str(exc)
        return True, "configured"

    def execute(self, task: TaskRecord, context: ProviderContext) -> TaskResult:
        start = time.monotonic()
        command = self._resolve_command()
        timeout = int(self.config.get("timeout_seconds", 300))
        prompt = (
            task.description
            + "\n\nWork only inside the current directory. Do not commit."
        )
        args = [command, "exec", "--sandbox", self._sandbox_mode(), prompt]
        backend = self._windows_sandbox_backend()
        if backend:
            # Explicit so the run does not depend on the machine's global
            # ~/.codex/config.toml, which the engine does not own.
            args[2:2] = ["-c", f'windows.sandbox="{backend}"']
        try:
            proc = subprocess.run(
                args,
                cwd=context.project_dir,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
                env=self._safe_env(command),
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"Codex timed out after {timeout}s") from exc
        status = "ok" if proc.returncode == 0 else "error"
        err = None if proc.returncode == 0 else proc.stderr[-4000:]
        return TaskResult(task.task_id, self.name, status, time.monotonic() - start, proc.stdout[-8000:], err)

    def _sandbox_mode(self) -> str:
        """The Codex sandbox policy for this run.

        `codex exec` defaults to `read-only`, so without an explicit
        `workspace-write` the agent cannot edit anything and the engine fails
        with "Provider completed without producing file changes".

        `workspace-write` lets Codex edit the working directory while keeping
        the configured sandbox boundaries. `danger-full-access` removes Codex's
        sandbox isolation: a Hybrid worktree still protects the project root
        from direct edits, but it does not constrain the process to that worktree
        at the operating-system level.

        This is a trusted-only setting: a project may not select its own sandbox
        mode (see TRUSTED_PROVIDER_FIELDS).
        """
        mode = str(self.config.get("sandbox", "workspace-write"))
        allowed = {"read-only", "workspace-write", "danger-full-access"}
        if mode not in allowed:
            raise ProviderError(f"Unknown codex sandbox mode {mode!r}. Allowed: {', '.join(sorted(allowed))}")
        return mode

    def _windows_sandbox_backend(self) -> str | None:
        """The Windows sandbox backend Codex should use, or None to leave it alone.

        Codex accepts `elevated`, `unelevated` and `mxc`. `elevated` is the one
        that actually restricts the filesystem, but on this machine it cannot
        provision (see below), and `unelevated` was measured to allow writes
        *outside* the workspace, so it is not an isolation boundary.

        The engine therefore passes an explicit value only when trusted config
        sets one, and defaults to `elevated` so the strict mode is the default
        and a weaker mode can never be selected by an untrusted project file.

        Known environmental failure, recorded here because it is not fixable
        from this module: `codex-windows-sandbox-setup.exe` fails to grant an ACL
        on `runtimes\\cua_node\\<hash>\\bin\\node_repl.exe` with
        "file is in use by another process (os error 32)", which makes the whole
        `setup refresh` fail with `helper_unknown_error` and disables shell
        execution and file writes. See docs/MASTER_CONFORMITY_RESULT.md § O.6.
        """
        if os.name != "nt":
            return None
        backend = str(self.config.get("windows_sandbox", "elevated"))
        allowed = {"elevated", "unelevated", "mxc"}
        if backend not in allowed:
            raise ProviderError(
                f"Unknown codex windows sandbox {backend!r}. Allowed: {', '.join(sorted(allowed))}"
            )
        return backend

    def probe_write(self, workdir: Path, filename: str = "hybrid-sandbox-probe.txt") -> tuple[bool, str]:
        """Prove the sandbox can actually write, instead of assuming it can.

        Returns (ok, detail). Runs a throwaway `codex exec` that creates one file
        in `workdir`. This is the only honest way to answer "is the sandbox
        working", because provisioning failures happen at exec time and leave no
        trace until something tries to write.
        """
        try:
            command = self._resolve_command()
        except ProviderError as exc:
            return False, str(exc)
        args = [command, "exec", "--skip-git-repo-check", "--sandbox", self._sandbox_mode()]
        backend = self._windows_sandbox_backend()
        if backend:
            args += ["-c", f'windows.sandbox="{backend}"']
        args.append(f"Create {filename} with the text ok")
        target = workdir / filename
        target.unlink(missing_ok=True)
        timeout = int(self.config.get("timeout_seconds", 300))
        try:
            proc = subprocess.run(
                args, cwd=workdir, text=True, encoding="utf-8", errors="replace",
                capture_output=True, timeout=timeout,
                check=False, env=self._safe_env(command),
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return False, f"probe could not run: {exc}"
        if target.is_file():
            return True, f"sandbox wrote {filename}"
        detail = ((proc.stdout or "") + (proc.stderr or "")).strip()
        for marker in ("helper_unknown_error", "setup refresh had errors", "denied", "Rejected"):
            if marker in detail:
                return False, f"sandbox write failed: {marker}"
        return False, f"sandbox write produced no file (exit {proc.returncode})"

    def _resolve_command(self) -> str:
        command = str(self.config.get("command", "codex"))
        if Path(command).is_absolute():
            resolved = Path(command)
            if not resolved.exists():
                raise ProviderError(f"{command} CLI not found")
            return str(resolved.resolve())
        if any(sep in command for sep in ("/", "\\")):
            raise ProviderError("Codex command must be a simple executable name or an absolute trusted path")
        resolved = shutil.which(command)
        if not resolved:
            raise ProviderError(f"{command} CLI not found")
        return str(Path(resolved).resolve())

    def _safe_env(self, command: str) -> dict[str, str]:
        trusted_names = self.config.get("trusted_env", [])
        if not isinstance(trusted_names, list):
            trusted_names = []
        env = {name: os.environ[name] for name in self.ENV_ALLOWED if name in os.environ}
        for name in trusted_names:
            if isinstance(name, str) and name in os.environ and not _looks_secret(name):
                env[name] = os.environ[name]
        command_dir = str(Path(command).parent)
        if os.name == "nt":
            # Windows tools look for their own DLLs and helpers through PATH.
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            safe_parts = [
                command_dir,
                str(Path(system_root) / "System32"),
                str(Path(system_root) / "System32" / "Wbem"),
                system_root,
            ]
        else:
            safe_parts = [command_dir, "/usr/local/bin", "/usr/bin", "/bin"]
        env["PATH"] = os.pathsep.join(dict.fromkeys(safe_parts))
        return env


def _looks_secret(name: str) -> bool:
    upper = name.upper()
    return any(marker in upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))

