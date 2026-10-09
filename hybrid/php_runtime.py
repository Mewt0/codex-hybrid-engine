"""Locate the PHP runtime a project actually targets.

Why this is not just `shutil.which("php")`: on the target machine PHP is not on
PATH at all. OSPanel keeps every build under `modules/php/PHP_x.y`, and the
project's real runtime is whichever build the site is served with. Picking "the
newest one available" (the previous behaviour) happens to be right today but is
wrong in general, and it silently lints code against a runtime the site does not
use — a legacy project can pass the quality gate and still fail in production.

Resolution order:

1. `HYBRID_PHP_BIN` - explicit override, for CI and for pinning a runtime.
2. `.php-version` / `.php_version` in the project root (one version, e.g. `8.1.9`).
3. `composer.json` `require.php` (e.g. `>=8.3`, `^8.1`, `8.1.*`) - satisfied by
   the *lowest* available build that meets it, because that is the stated floor
   the code promises to support.
4. `php` on PATH.
5. Highest available OSPanel build (last resort, reported as such).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

OSPANEL_ROOTS = (Path("E:/OSPanel/modules/php"), Path("C:/OSPanel/modules/php"))
_VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


@dataclass
class PhpRuntime:
    path: str
    version: tuple[int, ...] | None = None
    source: str = "unknown"

    @property
    def version_text(self) -> str:
        return ".".join(str(part) for part in self.version) if self.version else "unknown"


def _version_tuple(text: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups(default="0"))


def _version_from_directory(name: str) -> tuple[int, ...] | None:
    # "PHP_8.5.11" -> (8, 5, 11)
    match = re.search(r"PHP_(\d+)\.(\d+)(?:\.(\d+))?", name)
    if not match:
        return None
    return tuple(int(part) for part in match.groups(default="0"))


def available_builds() -> list[tuple[tuple[int, ...], Path]]:
    builds: list[tuple[tuple[int, ...], Path]] = []
    for root in OSPANEL_ROOTS:
        if not root.is_dir():
            continue
        for directory in root.iterdir():
            exe = directory / "php.exe"
            if not directory.is_dir() or not exe.is_file():
                continue
            version = _version_from_directory(directory.name)
            if version:
                builds.append((version, exe))
    return sorted(builds, key=lambda item: item[0])


def _composer_constraint(project_dir: Path) -> str | None:
    composer = project_dir / "composer.json"
    if not composer.is_file():
        return None
    try:
        data = json.loads(composer.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    require = data.get("require")
    if not isinstance(require, dict):
        return None
    php = require.get("php")
    return php if isinstance(php, str) else None


def _meets(version: tuple[int, ...], constraint: str) -> bool | None:
    """Return True/False, or None when the constraint cannot be interpreted."""
    text = constraint.strip()
    floor = _version_tuple(text)
    if floor is None:
        return None
    if any(token in text for token in (">=", "^", "~", "*", ">")):
        return version >= floor
    if "<" in text:
        return version < floor
    return version[: len(floor)] == floor


def resolve_php(project_dir: Path | None = None) -> PhpRuntime | None:
    override = os.environ.get("HYBRID_PHP_BIN")
    if override:
        path = Path(override)
        if path.is_file():
            return PhpRuntime(str(path), _version_from_directory(path.parent.name), "HYBRID_PHP_BIN")

    project_dir = Path(project_dir).resolve() if project_dir else None
    builds = available_builds()

    if project_dir:
        for marker in (".php-version", ".php_version"):
            candidate = project_dir / marker
            if candidate.is_file():
                wanted = _version_tuple(candidate.read_text(encoding="utf-8", errors="replace"))
                if wanted:
                    for version, exe in builds:
                        if version[: len(wanted)] == wanted:
                            return PhpRuntime(str(exe), version, marker)
        constraint = _composer_constraint(project_dir)
        if constraint:
            for version, exe in builds:
                if _meets(version, constraint):
                    return PhpRuntime(str(exe), version, f"composer.json require.php {constraint}")

    found = shutil.which("php")
    if found:
        return PhpRuntime(found, None, "PATH")

    if builds:
        version, exe = builds[-1]
        return PhpRuntime(str(exe), version, "newest OSPanel build (no project constraint)")

    return None


def php_binary(project_dir: Path | None = None) -> str | None:
    """Backwards-compatible helper returning just the executable path."""
    runtime = resolve_php(project_dir)
    return runtime.path if runtime else None
