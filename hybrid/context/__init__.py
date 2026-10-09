from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

# Profiles select the skill set and the context sections for a task. The names
# follow ai-stack/profiles/*.yaml so one library serves every provider.
PROFILES: dict[str, list[str]] = {
    "frontend": ["beautiful-game-ui", "frontend-development", "browser-testing"],
    "backend-php": ["php-legacy", "mysql-database", "security-review"],
    "database": ["mysql-database", "security-review"],
    "python-engine": ["python-engine", "systematic-debugging", "security-review"],
    "review": ["security-review", "systematic-debugging"],
    "fullstack-game": [
        "beautiful-game-ui",
        "frontend-development",
        "php-legacy",
        "mysql-database",
        "security-review",
        "browser-testing",
        "systematic-debugging",
    ],
}

# Keyword routing used when the caller does not pin a profile.
PROFILE_TRIGGERS: dict[str, tuple[str, ...]] = {
    "frontend": (
        "css", "html", "javascript", "js", "ui", "interface", "layout", "интерфейс",
        "кнопк", "вёрстк", "верстк", "адаптив", "скриншот", "инвентар", "панель", "анимац",
    ),
    "database": ("sql", "mysql", "query", "migration", "transaction", "бд", "база данных", "запрос"),
    "backend-php": ("php", "endpoint", "ajax", "session", "api", "авторизац", "сессия", "бэкенд"),
    "review": ("review", "audit", "проанализируй", "ревью", "аудит", "найди ошибк"),
    "python-engine": ("python", "модуль", "индекс", "состояние", "атомарн", "cli", "pytest", "движк"),
}

DESIGN_FILES = ("MASTER.md", "COLORS.md", "TYPOGRAPHY.md", "COMPONENTS.md", "LAYOUTS.md", "ANIMATIONS.md")

_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    body: str = ""
    path: Path | None = None


@dataclass
class ContextPack:
    task_id: str
    profile: str
    skills: list[Skill]
    sections: dict[str, str]
    files: list[tuple[str, str]]
    truncated: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    repo_map_summary: str = ""

    def prompt_text(self) -> str:
        return render_prompt(self)

    def skill_names(self) -> list[str]:
        return [skill.name for skill in self.skills]

    def used_files(self) -> list[str]:
        return [name for name, _ in self.files]


def parse_skill(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    name = path.parent.name
    description = ""
    triggers: list[str] = []
    body = text
    match = _FRONTMATTER.match(text)
    if match:
        body = text[match.end():]
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "name" and value:
                name = value
            elif key == "description":
                description = value
            elif key == "triggers":
                triggers = [item.strip().strip("[]\"'") for item in value.split(",") if item.strip()]
    return Skill(name=name, description=description, triggers=triggers, body=body.strip(), path=path)


class SkillLibrary:
    """Loads SKILL.md files from the project skill directory."""

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._cache: dict[str, Skill] | None = None

    def load(self) -> dict[str, Skill]:
        if self._cache is None:
            found: dict[str, Skill] = {}
            if self.skills_dir.is_dir():
                for skill_file in sorted(self.skills_dir.glob("*/SKILL.md")):
                    skill = parse_skill(skill_file)
                    found[skill.name] = skill
            self._cache = found
        return self._cache

    def names(self) -> list[str]:
        return sorted(self.load())

    def select(self, names: list[str]) -> list[Skill]:
        available = self.load()
        return [available[name] for name in names if name in available]


def choose_profile(description: str, forced: str | None = None) -> str:
    if forced:
        if forced not in PROFILES:
            raise ValueError(f"Unknown profile: {forced}. Known: {', '.join(sorted(PROFILES))}")
        return forced
    text = description.lower()
    for profile in ("database", "review", "frontend", "backend-php"):
        if any(trigger in text for trigger in PROFILE_TRIGGERS[profile]):
            return profile
    return "fullstack-game"


class ContextBuilder:
    """Builds one bounded Context Pack shared by every provider.

    The pack is assembled from the canonical project files plus the skills and
    design memory selected for the task profile. Only files allowed by the
    trusted configuration can ever be attached.
    """

    def __init__(self, settings, skill_library: SkillLibrary | None = None, repo_map=None):
        self.settings = settings
        self.root: Path = settings.root
        self.config = dict(settings.raw.get("ai_stack", {}))
        self.stack_dir = self._resolve_stack_dir()
        self.skills_dir = (self.stack_dir / self.config.get("skills_dir", "skills")).resolve()
        self.design_dir = (self.stack_dir / self.config.get("design_dir", "design")).resolve()
        self.profiles_dir = (self.stack_dir / self.config.get("profiles_dir", "profiles")).resolve()
        self.library = skill_library or SkillLibrary(self.skills_dir)
        self.repo_map = repo_map
        self.max_chars = int(settings.raw.get("context", {}).get("max_context_chars", 24000))
        self.max_file_chars = int(settings.raw.get("context", {}).get("max_file_chars", 12000))

    def _resolve_stack_dir(self) -> Path:
        """Find the shared AI stack.

        A project may carry its own `ai-stack/`; when it does not, the engine's
        own canonical library is used, so skills and design memory work for any
        target project and not only for the engine repository itself.
        """
        configured = self.config.get("root")
        if configured:
            stack_root = self.root / configured
            if stack_root.is_dir():
                return stack_root.resolve()
        local = self.root / "ai-stack"
        if local.is_dir():
            return local.resolve()
        engine = Path(__file__).resolve().parents[2] / "ai-stack"
        if engine.is_dir():
            return engine
        return local.resolve()

    # -- public API ---------------------------------------------------------

    def skills(self) -> dict[str, Skill]:
        return self.library.load()

    def profiles(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        if self.profiles_dir.is_dir():
            for profile_file in sorted(self.profiles_dir.glob("*.yaml")):
                found[profile_file.stem] = PROFILES.get(profile_file.stem, [])
        return found or dict(PROFILES)

    def build(self, task, profile: str | None = None) -> ContextPack:
        chosen = choose_profile(task.description, profile)
        skills = self.library.select(PROFILES.get(chosen, []))
        sections: dict[str, str] = {}
        missing: list[str] = []

        project_context = self._read_stack_file(self.config.get("project_context", "PROJECT_CONTEXT.md"))
        if project_context:
            sections["project_context"] = project_context
        else:
            missing.append("PROJECT_CONTEXT.md")

        if chosen in {"frontend", "fullstack-game", "review"}:
            design = self._design_block()
            if design:
                sections["design"] = design
            else:
                missing.append("design/MASTER.md")

        selected = self._select_files(chosen, task.description)
        files: list[tuple[str, str]] = []
        truncated: list[str] = []
        for rel, content in selected:
            if len(content) > self.max_file_chars:
                content = content[: self.max_file_chars] + "\n... [truncated]\n"
                truncated.append(rel)
            files.append((rel, content))

        pack = ContextPack(
            task_id=task.task_id,
            profile=chosen,
            skills=skills,
            sections=sections,
            files=files,
            truncated=truncated,
            missing=missing,
            repo_map_summary=self.repo_map.summary() if self.repo_map else "",
        )
        self._enforce_budget(pack)
        return pack

    # -- internals ----------------------------------------------------------

    def _read_stack_file(self, name: str) -> str | None:
        path = self.stack_dir / name
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        return None

    def _design_block(self) -> str:
        if not self.design_dir.is_dir():
            return ""
        parts: list[str] = []
        for name in DESIGN_FILES:
            path = self.design_dir / name
            if path.is_file():
                parts.append(path.read_text(encoding="utf-8").strip())
        return "\n\n".join(parts)

    def _select_files(self, profile: str, description: str = "") -> list[tuple[str, str]]:
        from .file_context import allowed_files, read_allowed_file

        allowed = allowed_files(self.settings)
        wanted = self._relevant_files(profile, description)
        chosen = [rel for rel in wanted if rel in allowed] if wanted else allowed
        result: list[tuple[str, str]] = []
        for rel in chosen:
            content = read_allowed_file(self.settings, rel)
            if content is not None:
                result.append((rel, content))
        return result

    def explain(self, description: str, profile: str | None = None, rejected: dict[str, str] | None = None):
        """Why these files, in this order, for this task.

        The same call the prompt build uses, so `hybrid context explain` can
        never describe a selection different from the one that gets attached.
        """
        from .file_context import allowed_files
        from .selection import select_files

        chosen = choose_profile(description, profile)
        return select_files(
            description,
            allowed_files(self.settings),
            repo_map=self.repo_map,
            profile=chosen,
            rejected=rejected,
        )

    def _relevant_files(self, profile: str, description: str = "") -> list[str]:
        """Order the allowed files for the task.

        With a repo map this is a real dependency walk (page -> asset -> AJAX
        endpoint -> SQL table); without one it degrades to the old extension
        hint, and says so in `hybrid context explain`.
        """
        from .file_context import allowed_files
        from .selection import select_files

        allowed = allowed_files(self.settings)
        if self.repo_map is not None or description:
            selection = select_files(description, allowed, repo_map=self.repo_map, profile=profile)
            return selection.paths()
        priority = {
            "frontend": (".css", ".js", ".html", ".php"),
            "backend-php": (".php", ".sql"),
            "database": (".sql", ".php"),
            "review": (".php", ".js", ".sql", ".css"),
            "fullstack-game": (".php", ".js", ".css", ".html", ".sql"),
        }.get(profile, (".php", ".js", ".css"))
        if self.repo_map:
            seeds = [rel for rel in allowed if Path(rel).suffix in priority and rel in self.repo_map.nodes]
            related: list[str] = []
            for rel in seeds:
                related.append(rel)
                related.extend(self.repo_map.related(rel))
            ordered_related = [rel for rel in dict.fromkeys(related) if rel in allowed]
            remainder = [rel for rel in allowed if rel not in set(ordered_related)]
            return ordered_related + sorted(remainder, key=lambda rel: (priority.index(Path(rel).suffix) if Path(rel).suffix in priority else len(priority), rel))
        ranked = sorted(allowed, key=lambda rel: (priority.index(Path(rel).suffix) if Path(rel).suffix in priority else len(priority), rel))
        return ranked

    def _enforce_budget(self, pack: ContextPack) -> None:
        def total() -> int:
            return len(render_prompt(pack))

        while total() > self.max_chars and pack.files:
            rel, _ = pack.files.pop()
            pack.truncated.append(rel)


def render_prompt(pack: ContextPack) -> str:
    """Render a context pack into the canonical prompt block."""
    parts: list[str] = []
    if pack.sections.get("project_context"):
        parts.append("# PROJECT CONTEXT\n\n" + pack.sections["project_context"])
    if pack.sections.get("design"):
        parts.append("# DESIGN SYSTEM\n\n" + pack.sections["design"])
    if pack.repo_map_summary:
        parts.append("# REPO MAP\n\n" + pack.repo_map_summary)
    if pack.skills:
        skill_blocks = [f"## Skill: {skill.name}\n\n{skill.body}" for skill in pack.skills]
        parts.append("# REQUIRED SKILLS\n\n" + "\n\n".join(skill_blocks))
    if pack.files:
        file_blocks = [f"### FILE: {rel}\n\n```\n{content}\n```" for rel, content in pack.files]
        parts.append("# PROJECT FILES (read-only context)\n\n" + "\n\n".join(file_blocks))
    return "\n\n".join(parts)
