"""Build a complete prompt pack for an external web chat.

The web model has no filesystem and no tools, so it gets everything it needs in
one message: a project card, the curated source files, the relevant skills, the
design rules and a strict output contract.

    pack = ContextPackWriter(settings).build(task, profile, files=["a.py"])
    Path("prompt.md").write_text(pack.text, encoding="utf-8", newline="\\n")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess

from . import ContextBuilder, PROFILES, choose_profile

SKIP_DIRS = {".git", ".hybrid", ".venv", "__pycache__", ".pytest_cache", "node_modules", "dist", "build"}
CODE_SUFFIXES = {".py", ".php", ".js", ".css", ".html", ".sql", ".yaml", ".yml", ".toml", ".json", ".md"}

OUTPUT_CONTRACT = """## Формат ответа

Верни **ровно** эти файлы, каждый целиком, без «...» и без сокращений:

```
## FILE: <путь относительно корня проекта>
<полный код файла>

## FILE: tests/<имя>.py
<полный код теста>
```

Потом коротко:

```
## HOW TO RUN
<точные команды>

## WHAT WORKS
<что реально реализовано>

## LIMITATIONS
<что не проверено и какие проверки не выполнены>
```

Правила: только стандартная библиотека Python 3.11+, никаких новых зависимостей,
текст в UTF-8 с LF, неисполненная проверка помечается SKIP/NOT RUN, а не PASS."""


@dataclass
class PromptPack:
    task_id: str
    profile: str
    skills: list[str] = field(default_factory=list)
    files: list[tuple[str, int]] = field(default_factory=list)
    text: str = ""
    truncated: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "profile": self.profile,
            "skills": self.skills,
            "files": [{"path": path, "bytes": size} for path, size in self.files],
            "chars": len(self.text),
            "truncated": self.truncated,
            "missing": self.missing,
        }


class ContextPackWriter:
    """Assembles the full message: project card + files + skills + contract."""

    def __init__(self, settings, context_builder: ContextBuilder | None = None):
        self.settings = settings
        self.context_builder = context_builder or ContextBuilder(settings)
        self.max_file_chars = int(settings.raw.get("context", {}).get("max_file_chars", 12000))
        # A web model has no filesystem, so a pack is intentionally larger than
        # the cloud-context default. Still bounded, and every file is listed.
        self.max_total_chars = int(settings.raw.get("context", {}).get("max_pack_chars", 80000))

    # -- public API ---------------------------------------------------------

    def project_card(self) -> str:
        root = Path(self.settings.root)
        counts: dict[str, int] = {}
        total_lines = 0
        for path in self._walk(root):
            suffix = path.suffix.lower()
            counts[suffix] = counts.get(suffix, 0) + 1
            try:
                total_lines += sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
            except OSError:
                continue
        languages = ", ".join(f"{suffix or '(no ext)'} x{count}" for suffix, count in sorted(counts.items(), key=lambda item: -item[1])[:8])
        tests = len(list((root / "tests").glob("test_*.py"))) if (root / "tests").is_dir() else 0
        return "\n".join(
            [
                "# КАРТОЧКА ПРОЕКТА",
                f"Корень: {root}",
                f"Git: {self._git(root)}",
                f"Файлы: {sum(counts.values())}, строк: {total_lines}",
                f"Языки: {languages}",
                f"Тесты: {tests} файлов в tests/",
                "Правила: только стандартная библиотека, атомарная запись состояния, LF, "
                "неисполненная проверка = SKIP/NOT RUN, секреты не читаются и не сохраняются.",
            ]
        )

    def build(self, task, profile: str | None = None, files: list[str] | None = None) -> PromptPack:
        chosen = choose_profile(task.description, profile)
        selected = files if files is not None else list(self.context_builder.skills() and [])
        pack = PromptPack(task_id=task.task_id, profile=chosen)

        skills = self.context_builder.library.select(PROFILES.get(chosen, []))
        pack.skills = [skill.name for skill in skills]

        parts: list[str] = [self.project_card(), "---", "# ЗАДАЧА", task.description, "---"]

        if skills:
            body = "\n\n".join(f"## Навык: {skill.name}\n\n{skill.body}" for skill in skills)
            parts += ["# НАВЫКИ, КОТОРЫМ НУЖНО СЛЕДОВАТЬ", body, "---"]

        design = self.context_builder._design_block() if chosen in {"frontend", "fullstack-game"} else ""
        if design:
            parts += ["# ДИЗАЙН-СИСТЕМА (не выдумывать новый стиль)", design, "---"]

        if selected:
            blocks: list[str] = []
            budget = self.max_total_chars
            for rel in selected:
                content = self._read(rel)
                if content is None:
                    pack.missing.append(rel)
                    continue
                if len(content) > self.max_file_chars:
                    content = content[: self.max_file_chars] + "\n... [обрезано]\n"
                    pack.truncated.append(rel)
                if len(content) > budget:
                    pack.truncated.append(rel)
                    continue
                budget -= len(content)
                blocks.append(f"## ФАЙЛ: {rel}\n\n```{Path(rel).suffix.lstrip('.')}\n{content}\n```")
                pack.files.append((rel, len(content)))
            parts += ["# СУЩЕСТВУЮЩИЙ КОД (обязателен к сохранению совместимости)", "\n\n".join(blocks), "---"]

        parts.append(OUTPUT_CONTRACT)
        pack.text = "\n\n".join(parts)
        return pack

    # -- internals ----------------------------------------------------------

    def _read(self, rel: str) -> str | None:
        root = Path(self.settings.root).resolve()
        path = (root / rel).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        if not path.is_file() or path.is_symlink():
            return None
        try:
            return path.read_text(encoding="utf-8", errors="replace").rstrip() + "\n"
        except OSError:
            return None

    def _walk(self, root: Path):
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix.lower() not in CODE_SUFFIXES:
                continue
            yield path

    def _git(self, root: Path) -> str:
        try:
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, text=True, capture_output=True, timeout=10, check=False).stdout.strip()
            commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True, capture_output=True, timeout=10, check=False).stdout.strip()
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, timeout=10, check=False).stdout.strip()
            return f"{branch} @ {commit}{' (dirty)' if dirty else ' (clean)'}"
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
