from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import threading
import time
from types import ModuleType
from typing import Any


SDK_MODULE = "deepseek_harness_sdk"


@dataclass
class HarnessResult:
    status: str
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0


class DeepSeekHarnessAdapter:
    name = "deepseek_harness"

    def __init__(self, config: dict):
        self.config = config
        self._semaphore = threading.BoundedSemaphore(int(config.get("max_parallel_agents", 1)))

    def available(self) -> tuple[bool, str]:
        if not self.config.get("enabled", False):
            return False, "disabled by configuration"
        try:
            module = _load_sdk()
        except HarnessSdkUnavailable as exc:
            return False, str(exc)
        version = getattr(module, "__version__", None)
        if version:
            return True, f"{SDK_MODULE} {version}"
        return True, f"{SDK_MODULE} importable; interface name is unverified"

    def run_task(self, description: str, cwd: Path, timeout: int | None = None) -> HarnessResult:
        start = time.monotonic()
        if not self.config.get("enabled", False):
            return HarnessResult("unavailable", error="disabled by configuration")
        if os.environ.get("HYBRID_INSIDE_AGENT") == "1":
            return HarnessResult("error", error="recursive harness execution is disabled")
        try:
            module = _load_sdk()
        except HarnessSdkUnavailable as exc:
            return HarnessResult("unavailable", error=str(exc), duration_seconds=time.monotonic() - start)

        effective_timeout = int(timeout if timeout is not None else self.config.get("timeout_seconds", 180))
        if not self._semaphore.acquire(blocking=False):
            return HarnessResult("error", error="max_parallel_agents limit reached", duration_seconds=time.monotonic() - start)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_invoke_sdk, module, description, cwd, self._safe_env())
        try:
            try:
                output = future.result(timeout=effective_timeout)
            except FutureTimeoutError:
                future.cancel()
                return HarnessResult(
                    "error",
                    error=f"deepseek harness timed out after {effective_timeout}s",
                    duration_seconds=time.monotonic() - start,
                )
            except HarnessSdkError as exc:
                return HarnessResult("error", error=str(exc), duration_seconds=time.monotonic() - start)
            return HarnessResult("ok", output=output, duration_seconds=time.monotonic() - start)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            self._semaphore.release()

    def _safe_env(self) -> dict[str, str]:
        allowed = {
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "TEMP",
            "TMP",
            "TMPDIR",
            "USER",
            "USERNAME",
            "SHELL",
            "SYSTEMROOT",
            "WINDIR",
        }
        return {name: os.environ[name] for name in allowed if name in os.environ}


class HarnessSdkUnavailable(RuntimeError):
    pass


class HarnessSdkError(RuntimeError):
    pass


def _load_sdk() -> ModuleType:
    try:
        return importlib.import_module(SDK_MODULE)
    except ImportError as exc:
        raise HarnessSdkUnavailable("deepseek-harness-sdk is not installed") from exc


def _invoke_sdk(module: ModuleType, description: str, cwd: Path, env: dict[str, str]) -> str:
    runner = getattr(module, "run_task", None) or getattr(module, "run", None)
    if not callable(runner):
        raise HarnessSdkError("deepseek harness SDK interface is not verified")
    result = runner(description=description, cwd=Path(cwd), env=env)
    return _result_output(result)


def _result_output(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    output = getattr(result, "output", None)
    if output is not None:
        return str(output)
    return str(result)
