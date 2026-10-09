from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
import shutil
import subprocess
import json

from hybrid.php_runtime import resolve_php


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""


def validate_paths(project_dir: Path, changed: list[str], config: dict) -> list[CheckResult]:
    results: list[CheckResult] = []
    forbidden = config.get("forbidden_paths", [])
    sensitive_markers = ("secret", "token", "credential", "password", "private")
    max_files = int(config.get("max_files_changed", 5))
    if len(changed) > max_files:
        results.append(CheckResult("Architecture: max files", "FAIL", f"{len(changed)} > {max_files}"))
    for rel in changed:
        if any(p.is_symlink() for p in [(project_dir / rel), *(project_dir / rel).parents] if p != project_dir.parent):
            results.append(CheckResult("Architecture: symlink", "FAIL", rel))
        candidate = (project_dir / rel).resolve()
        try:
            candidate.relative_to(project_dir.resolve())
        except ValueError:
            results.append(CheckResult("Architecture: path boundary", "FAIL", rel))
        if ".." in Path(rel).parts:
            results.append(CheckResult("Architecture: parent traversal", "FAIL", rel))
        if any(fnmatch(rel, pattern) for pattern in forbidden):
            results.append(CheckResult("Architecture: forbidden path", "FAIL", rel))
        lowered = rel.lower()
        if any(marker in lowered for marker in sensitive_markers):
            results.append(CheckResult("Architecture: sensitive path", "FAIL", rel))
        if rel.endswith("/..."):
            results.append(CheckResult("Architecture: unsupported change set", "FAIL", rel))
    if not any(r.status == "FAIL" and r.name.startswith("Architecture") for r in results):
        results.append(CheckResult("Architecture Rules", "PASS", "changed paths allowed"))
    return results


def php_binary(project_dir: Path | None = None) -> str | None:
    """Locate the PHP runtime for a project.

    Delegates to `hybrid.php_runtime`, which honours an explicit override, a
    `.php-version` marker and `composer.json`'s `require.php`. Passing the
    project directory matters: without it the resolver falls back to the newest
    installed build, which can lint code against a runtime the site never uses.
    """
    from hybrid.php_runtime import php_binary as _resolve

    return _resolve(project_dir)


def run_quality(project_dir: Path, changed: list[str]) -> list[CheckResult]:
    results = [_run(["git", "diff", "--check", "HEAD"], project_dir, "Git Diff")]
    runtime = resolve_php(project_dir)
    php = runtime.path if runtime else None
    php_files = [f for f in changed if f.endswith(".php") and (project_dir / f).is_file()]
    if php_files and php:
        # Record which runtime linted the file. During a PHP version migration a
        # bare "PASS" is ambiguous: 8.1-clean and 8.5-clean are different claims.
        for rel in php_files:
            result = _run([php, "-l", rel], project_dir, f"PHP Syntax: {rel}")
            result.detail = f"PHP {runtime.version_text} ({runtime.source}) | {result.detail}"
            results.append(result)
    elif php_files:
        results.append(CheckResult("PHP Syntax", "SKIP", "php executable not found"))
    js_files = [f for f in changed if f.endswith((".js", ".mjs", ".cjs")) and (project_dir / f).is_file()]
    if js_files and shutil.which("node"):
        for rel in js_files:
            results.append(_run(["node", "--check", rel], project_dir, f"JS Syntax: {rel}"))
    elif js_files:
        results.append(CheckResult("JS Syntax", "SKIP", "node executable not found"))
    results.append(CheckResult("Behavior Tests", "NOT AVAILABLE", "no project test command configured"))
    results.append(CheckResult("Review Required", "YES", "manual approval required before apply"))
    return results


def _run(args: list[str], cwd: Path, name: str) -> CheckResult:
    try:
        proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False, timeout=30)
    except subprocess.TimeoutExpired:
        return CheckResult(name, "FAIL", "Check timed out")
    status = "PASS" if proc.returncode == 0 else "FAIL"
    return CheckResult(name, status, (proc.stdout + proc.stderr).strip()[-2000:])


def validate_dependencies(root: Path, changed: list[str], config: dict) -> list[CheckResult]:
    if config.get("allow_new_dependencies", False):
        return []
    results = []
    for rel in changed:
        name = Path(rel).name
        if name not in {"package.json", "composer.json"} or not (root / rel).is_file():
            continue
        fields = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies") if name == "package.json" else ("require", "require-dev")
        try:
            old = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root, capture_output=True, text=True, check=False)
            before = json.loads(old.stdout) if old.returncode == 0 else {}
            after = json.loads((root / rel).read_text(encoding="utf-8"))
            added = []
            for field in fields:
                previous, current = before.get(field, {}), after.get(field, {})
                if not isinstance(previous, dict) or not isinstance(current, dict):
                    raise ValueError("Dependency sections must be objects")
                added.extend(f"{field}:{key}" for key in current if key not in previous or current[key] != previous[key])
            results.append(CheckResult(f"Dependencies: {rel}", "FAIL" if added else "PASS", ", ".join(added)))
        except (ValueError, OSError, AttributeError) as exc:
            results.append(CheckResult(f"Dependencies: {rel}", "FAIL", str(exc)))
    return results

