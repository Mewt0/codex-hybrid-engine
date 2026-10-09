from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

MAX_FILE_CHARS = 12000
MAX_FILES = 8
MAX_TOTAL_CHARS = 80000

SECRET_NAMES = {".env", ".env.local", "secrets.json", "credentials.json"}
SECRET_MARKERS = ("secret", "token", "credential", "password", "private")
SENSITIVE_DIRS = {"config", "configs", "configuration", "sessions", ".git", ".hybrid"}


def allowed_files(settings) -> list[str]:
    """Return the trusted allow-list of project-relative files.

    Only the trusted user configuration can grant cloud/browser context; a
    project settings file can narrow the list but never widen it.
    """
    entries = settings.raw.get("context", {}).get("allowed_files", [])
    result: list[str] = []
    for item in entries:
        if not isinstance(item, str) or not item:
            continue
        if _is_sensitive(item):
            continue
        result.append(Path(item).as_posix())
    return sorted(dict.fromkeys(result))


def read_allowed_file(settings, rel: str) -> str | None:
    """Read one allowed file, refusing paths that escape or look sensitive."""
    if _is_sensitive(rel):
        return None
    root = settings.root.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file() or candidate.is_symlink():
        return None
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + "\n... [truncated]\n"
    return text


def _is_sensitive(rel: str) -> bool:
    path = Path(rel)
    lowered = rel.lower()
    if path.name in SECRET_NAMES or path.name.lower().startswith(".env"):
        return True
    if any(part.lower() in SENSITIVE_DIRS for part in path.parts[:-1]):
        return True
    return any(marker in lowered for marker in SECRET_MARKERS)


def forbidden_patterns(settings) -> list[str]:
    return list(settings.raw.get("architecture", {}).get("forbidden_paths", []))


def is_forbidden(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel, pattern) for pattern in patterns)
