"""Task-aware file selection driven by the repository map.

The engine used to hand a provider the first few files it found by walking the
project alphabetically, capped by extension and size. That is why "make the
inventory responsive" could send `README.md` and `package.json` while the actual
inventory page, its stylesheet, its AJAX endpoint and the SQL schema were left
out.

This module answers one question: *given this task, which allowed files belong
together, and why?* It scores the task text against file paths, the symbols the
repo map extracted (functions, classes, tables, CSS classes) and the links
between files, then expands the winners along real dependencies.

Everything here is pure: it takes the trusted allow-list and an optional
:class:`~hybrid.context.repo_map.RepoMap` and returns a :class:`Selection` with a
human-readable reason per file, so `hybrid context explain` and the prompt build
cannot disagree about what was chosen or why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .repo_map import REL_DEPENDENT, REL_INDEPENDENT, RepoMap

TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+")

# Words that carry no selection signal: they appear in almost every task.
STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "make", "made", "add", "fix", "fixes", "update", "updates",
        "change", "changes", "new", "old", "use", "using", "from", "into", "that", "this", "all",
        "code", "file", "files", "page", "pages", "please", "should", "must", "need", "needs",
        "сделай", "сделать", "нужно", "надо", "добавь", "добавить", "исправь", "исправить",
        "обнови", "обновить", "поменяй", "измени", "изменить", "файл", "файлы", "страниц",
        "страница", "страницы", "код", "весь", "все", "для", "что", "чтобы", "это", "как",
    }
)

# A file that is only linked to a seed is worth less than the seed itself.
RELATED_WEIGHT = 0.5
# Extension preference per profile, used only to break ties and order the tail.
PROFILE_PRIORITY: dict[str, tuple[str, ...]] = {
    "frontend": (".css", ".js", ".html", ".php"),
    "backend-php": (".php", ".sql"),
    "database": (".sql", ".php"),
    "python-engine": (".py", ".md"),
    "review": (".php", ".js", ".sql", ".css"),
    "fullstack-game": (".php", ".js", ".css", ".html", ".sql"),
}


def task_tokens(description: str) -> list[str]:
    """Lower-cased, de-duplicated words of the task that carry selection signal."""
    seen: list[str] = []
    for match in TOKEN_RE.finditer((description or "").lower()):
        token = match.group(0)
        if len(token) < 3 or token in STOPWORDS or token.isdigit():
            continue
        if token not in seen:
            seen.append(token)
    return seen


def _stem(token: str) -> str:
    """Crude stemmer: enough to match "inventory" against "inventories"."""
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


@dataclass
class FileChoice:
    path: str
    score: float
    reason: str
    links: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"- {self.path}", f"    reason: {self.reason}"]
        for link in self.links:
            lines.append(f"    link: {link}")
        return "\n".join(lines)


@dataclass
class Selection:
    profile: str
    repo_map_used: bool
    choices: list[FileChoice] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def paths(self) -> list[str]:
        return [choice.path for choice in self.choices]

    def reason_for(self, path: str) -> str:
        for choice in self.choices:
            if choice.path == path:
                return choice.reason
        return ""

    def render(self) -> str:
        lines = [f"Profile: {self.profile}"]
        lines.append(f"Repo map: {'used' if self.repo_map_used else 'not available'}")
        if self.tokens:
            lines.append(f"Task tokens: {', '.join(self.tokens)}")
        lines.append("")
        lines.append(f"Selected files ({len(self.choices)}):")
        lines.extend(choice.render() for choice in self.choices)
        if self.excluded:
            lines.append("")
            lines.append(f"Excluded files ({len(self.excluded)}):")
            for path, why in self.excluded:
                lines.append(f"- {path}")
                lines.append(f"    reason: {why}")
        return "\n".join(lines)


def _symbol_score(node, stems: set[str]) -> tuple[float, list[str]]:
    """How many of the task words name something this file actually defines."""
    score = 0.0
    hits: list[str] = []
    for symbol in node.symbols:
        name = symbol.name.lower().lstrip(".")
        if symbol.kind == "request-param":
            name = name.split(":", 1)[-1]
        if symbol.kind == "sql-table":
            name = name.split(":", 1)[-1]
        if not name:
            continue
        if _stem(name) in stems or name in stems:
            score += 2.0
            hits.append(symbol.name)
    return score, hits


def _path_score(path: str, stems: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    hits: list[str] = []
    for part in Path(path).with_suffix("").parts:
        for word in re.split(r"[^A-Za-zА-Яа-я0-9]+", part.lower()):
            if word and (_stem(word) in stems or word in stems):
                score += 3.0
                hits.append(word)
    return score, hits


def _dependent_links(repo_map: RepoMap, path: str) -> list[str]:
    links: list[str] = []
    for key, relation in repo_map.relations.items():
        if relation != REL_DEPENDENT or " -> " not in key:
            continue
        left, right = key.split(" -> ", 1)
        if left == path:
            links.append(right)
        elif right == path:
            links.append(left)
    return sorted(set(links))


def _priority_index(profile: str, path: str) -> int:
    order = PROFILE_PRIORITY.get(profile, (".php", ".js", ".css", ".sql"))
    suffix = Path(path).suffix.lower()
    return order.index(suffix) if suffix in order else len(order)


def select_files(
    description: str,
    allowed: list[str],
    repo_map: RepoMap | None = None,
    profile: str | None = None,
    limit: int = 12,
    rejected: dict[str, str] | None = None,
) -> Selection:
    """Rank the allowed files for one task and explain every decision.

    The allow-list is the only source of candidates: a repo-map link can promote
    an allowed file, never introduce a file the trusted configuration did not
    permit.
    """
    if profile is None:
        from . import choose_profile

        profile = choose_profile(description)

    tokens = task_tokens(description)
    stems = {_stem(token) for token in tokens}
    universe = sorted(dict.fromkeys(path for path in allowed if path))
    selection = Selection(
        profile=profile,
        repo_map_used=repo_map is not None,
        tokens=tokens,
        excluded=sorted((rejected or {}).items()),
    )

    if not universe:
        selection.excluded.append(("(project)", "context.allowed_files is empty: nothing may be attached"))
        return selection

    scores: dict[str, float] = {}
    reasons: dict[str, tuple[str, list[str]]] = {}
    for path in universe:
        score = 0.0
        notes: list[str] = []
        node = repo_map.nodes.get(path) if repo_map else None
        if stems:
            file_score, file_hits = _path_score(path, stems)
            if file_hits:
                score += file_score
                notes.append(f"path matches {', '.join(sorted(set(file_hits)))}")
            if node is not None:
                symbol_score, symbol_hits = _symbol_score(node, stems)
                if symbol_hits:
                    score += symbol_score
                    notes.append(f"defines {', '.join(sorted(set(symbol_hits))[:4])}")
        if node is not None and repo_map is not None:
            linked = _dependent_links(repo_map, path)
            if linked and score > 0:
                notes.append(f"linked to {', '.join(linked[:3])}")
        # A tiny profile preference keeps the tail stable without outranking a
        # real task match.
        score += max(0.0, 0.2 - 0.01 * _priority_index(profile, path))
        scores[path] = score
        reasons[path] = ("; ".join(notes), [])

    seeds = sorted((path for path in universe if scores[path] > 0.2), key=lambda p: (-scores[p], p))
    chosen: dict[str, FileChoice] = {}
    for path in seeds:
        note, links = reasons[path]
        chosen[path] = FileChoice(
            path=path,
            score=scores[path],
            reason=f"matches the task ({note})" if note else "matches the task",
            links=links,
        )

    # Expand along real dependencies: a stylesheet referenced by the page that
    # the task mentions belongs in the same request, even if the task never
    # names it.
    if repo_map is not None:
        for seed in list(chosen):
            seed_choice = chosen[seed]
            for neighbour in repo_map.related(seed, depth=2):
                if neighbour not in universe or neighbour in chosen:
                    continue
                relation = _relation_between(repo_map, seed, neighbour)
                if relation == REL_INDEPENDENT:
                    continue
                chosen[neighbour] = FileChoice(
                    path=neighbour,
                    score=seed_choice.score * RELATED_WEIGHT,
                    reason=(
                        f"linked to {seed} ({relation})"
                        + (", which matches the task" if seed in seeds else "")
                    ),
                )

    remainder = [
        path
        for path in sorted(universe, key=lambda p: (_priority_index(profile, p), p))
        if path not in chosen
    ]
    result = sorted(chosen.values(), key=lambda choice: (-choice.score, choice.path))
    for path in remainder:
        if len(result) >= limit:
            break
        result.append(
            FileChoice(path=path, score=0.0, reason="allowed file; no link to the task text was found")
        )

    selection.choices = result[:limit]
    kept = {choice.path for choice in selection.choices}
    for path in universe:
        if path in kept:
            continue
        selection.excluded.append(
            (path, "allowed, but beyond the selection limit" if scores.get(path, 0) > 0.2 else "no link to the task text")
        )
    return selection


def _relation_between(repo_map: RepoMap, left: str, right: str) -> str:
    key = f"{left} -> {right}" if left < right else f"{right} -> {left}"
    return repo_map.relations.get(key, REL_INDEPENDENT)
