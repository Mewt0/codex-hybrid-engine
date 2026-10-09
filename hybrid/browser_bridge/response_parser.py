from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from pathlib import Path, PurePosixPath

from hybrid.context.file_context import forbidden_patterns, is_forbidden
from hybrid.quality.checks import CheckResult

SECTION_RE = re.compile(r"^\s{0,3}#{1,6}\s*([A-Za-z][A-Za-z _/-]{1,40})\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.DOTALL)
DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$", re.MULTILINE)
OLD_FILE_RE = re.compile(r"^--- (?:a/)?(.+?)\s*$", re.MULTILINE)
NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$", re.MULTILINE)
SHELL_HINT_RE = re.compile(
    r"(?im)^\s*(?:\$|>)\s*(?:git|php|npm|composer|mysql|cd|rm|mv|curl|wget|powershell)\b"
)

PATCH_LANGUAGES = {"diff", "patch"}
SENSITIVE_SEGMENTS = {".env", ".hybrid", "config/secrets", "tests/protected"}


@dataclass
class ParsedResponse:
    task_id: str
    sections: dict[str, str] = field(default_factory=dict)
    patch: str | None = None
    patch_blocks: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    response_sha256: str = ""
    is_patch: bool = False
    warnings: list[str] = field(default_factory=list)

    def section(self, name: str) -> str:
        return self.sections.get(name.upper(), "")

    def summary(self) -> str:
        return self.section("SUMMARY") or self.sections.get("PREAMBLE", "").strip()


class ResponseParser:
    """Parses a pasted web-chat answer and validates any proposed patch."""

    def parse(self, task_id: str, text: str) -> ParsedResponse:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        parsed = ParsedResponse(
            task_id=task_id,
            response_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        )
        parsed.sections = self._split_sections(normalized)
        parsed.patch_blocks = [
            body.lstrip("\n")
            for language, body in self._fences(normalized)
            if language in PATCH_LANGUAGES and body.strip()
        ]

        if not parsed.patch_blocks:
            parsed.warnings.append("No diff block found; the answer is stored as an analysis, not a patch.")
            return parsed

        if len(parsed.patch_blocks) > 1:
            parsed.warnings.append(
                f"{len(parsed.patch_blocks)} diff blocks found; only the first is used and the rest are preserved in the raw answer."
            )

        patch = parsed.patch_blocks[0]
        # The trailing newline is part of a valid unified diff: stripping it
        # makes git report "corrupt patch" on the last hunk line.
        patch = patch.replace("\r\n", "\n")
        if not patch.endswith("\n"):
            patch += "\n"
        parsed.patch = patch
        if not patch.lstrip().startswith("diff --git"):
            parsed.warnings.append("The patch does not start with `diff --git`; it was not treated as an applicable diff.")
            parsed.patch = None
            return parsed

        parsed.is_patch = True
        parsed.files = self._patch_paths(patch)
        if not parsed.files:
            parsed.warnings.append("The patch names no files; path checks could not run.")
        if SHELL_HINT_RE.search(normalized):
            parsed.warnings.append(
                "The answer contains shell-looking lines. They are shown to you as text and are never executed by the engine."
            )
        if not parsed.sections.get("SUMMARY"):
            parsed.warnings.append("No SUMMARY section found in the answer.")
        return parsed

    def validate_patch(self, parsed: ParsedResponse, settings, project_dir: Path) -> list[CheckResult]:
        results: list[CheckResult] = []
        if not parsed.is_patch or not parsed.patch:
            return [CheckResult("Response Format", "FAIL", "No unified diff found in the response.")]

        results.append(CheckResult("Response Format", "PASS", f"sections: {', '.join(sorted(parsed.sections)) or 'none'}"))

        if not parsed.patch.lstrip().startswith("diff --git"):
            return results + [CheckResult("Patch Format", "FAIL", "Patch must be a unified diff starting with `diff --git`.")]

        blocked: list[str] = []
        patterns = forbidden_patterns(settings)
        root = Path(project_dir).resolve()
        for rel in parsed.files:
            # Windows and GitHub-style patches mix separators and case: reject
            # `CONFIG/SECRETS/key.php` exactly like `config/secrets/key.php`.
            normalized = rel.replace("\\", "/")
            lowered = normalized.lower()
            parts = PurePosixPath(normalized).parts
            if normalized.startswith("/") or ".." in parts:
                blocked.append(f"{rel} (path escapes the project)")
                continue
            if any(segment in lowered for segment in SENSITIVE_SEGMENTS):
                blocked.append(f"{rel} (protected path)")
                continue
            if is_forbidden(normalized, patterns) or is_forbidden(lowered, patterns):
                blocked.append(f"{rel} (forbidden by configuration)")
                continue
            try:
                (root / normalized).resolve().relative_to(root)
            except ValueError:
                blocked.append(f"{rel} (resolves outside the project)")

        if blocked:
            results.append(CheckResult("Patch Paths", "FAIL", "; ".join(blocked)))
        else:
            results.append(CheckResult("Patch Paths", "PASS", ", ".join(parsed.files) or "no files listed"))
        results.append(CheckResult("Patch Format", "PASS", f"{len(parsed.patch.splitlines())} lines"))
        return results

    # -- internals ----------------------------------------------------------

    def _split_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        matches = list(SECTION_RE.finditer(text))
        if not matches:
            sections["PREAMBLE"] = text.strip()
            return sections
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections["PREAMBLE"] = preamble
        for index, match in enumerate(matches):
            name = match.group(1).strip().upper()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = text[match.end():end].strip()
            if name in sections:
                sections[name] = sections[name] + "\n\n" + body
            else:
                sections[name] = body
        return sections

    def _fences(self, text: str) -> list[tuple[str, str]]:
        return [(match.group(1).lower(), match.group(2)) for match in FENCE_RE.finditer(text)]

    def _patch_paths(self, patch: str) -> list[str]:
        """Collect every path the patch mentions.

        Both sides of `diff --git`, plus the `---`/`+++` headers, because a
        deletion or a rename puts the protected path on the old side only. The
        early rejection must not be weaker than what git will later do.
        """
        found: list[str] = []
        for old_path, new_path in DIFF_HEADER_RE.findall(patch):
            self._add_patch_path(found, old_path)
            self._add_patch_path(found, new_path)
        for match in OLD_FILE_RE.findall(patch):
            self._add_patch_path(found, match)
        for match in NEW_FILE_RE.findall(patch):
            self._add_patch_path(found, match)
        return sorted(dict.fromkeys(found))

    def _add_patch_path(self, found: list[str], path: str) -> None:
        candidate = path.strip()
        if candidate in {"", "/dev/null"}:
            return
        if candidate.startswith(("a/", "b/")):
            candidate = candidate[2:]
        found.append(candidate)
