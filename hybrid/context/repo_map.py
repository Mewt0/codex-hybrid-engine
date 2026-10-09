from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import time
from typing import Any


REL_DEPENDENT = "dependent"
REL_INDEPENDENT = "independent"
REL_UNKNOWN = "unknown"

LANGUAGE_BY_SUFFIX = {
    ".php": "php",
    ".js": "js",
    ".css": "css",
    ".html": "html",
    ".htm": "html",
    ".sql": "sql",
}
SKIPPED_DIRS = {"node_modules", "vendor", ".git", ".hybrid", "dist", "build", ".venv"}
MAX_FILE_BYTES = 256 * 1024
MAX_FILE_LINES = 20_000

PHP_FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.IGNORECASE)
PHP_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)
PHP_CONST_RE = re.compile(r"\b(?:const\s+|define\s*\(\s*['\"])([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)
PHP_INCLUDE_RE = re.compile(r"\b(?:include|include_once|require|require_once)\s*(?:\(?\s*)['\"]([^'\"]+)['\"]", re.IGNORECASE)
PHP_SUPERGLOBAL_RE = re.compile(r"\$_(?:GET|POST|REQUEST)\s*\[\s*['\"]([^'\"]+)['\"]\s*\]", re.IGNORECASE)
JS_FUNCTION_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
JS_CONST_FUNCTION_RE = re.compile(r"\bconst\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:\([^)]*\)\s*=>|function\b)")
JS_IMPORT_RE = re.compile(r"\bimport\s+(?:[^'\"\n]+?\s+from\s+)?['\"]([^'\"]+)['\"]")
JS_DYNAMIC_IMPORT_RE = re.compile(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
JS_ENDPOINT_RE = re.compile(
    r"\b(?:fetch|\$\.post|\$\.get|\$\.ajax|XMLHttpRequest\s*\(\s*\)\s*\.open)\s*\(\s*(?:['\"][A-Z]+['\"]\s*,\s*)?['\"]([^'\"]+)['\"]",
)
JS_SELECTOR_RE = re.compile(r"\b(?:querySelector|querySelectorAll|getElementsByClassName)\s*\(\s*['\"]([^'\"]+)['\"]")
CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?['\"]([^'\"]+)['\"]")
CSS_CLASS_RE = re.compile(r"(?m)^\s*\.([A-Za-z_-][A-Za-z0-9_-]*)\b")
HTML_SCRIPT_RE = re.compile(r"<script\b[^>]*\bsrc\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
HTML_STYLESHEET_RE = re.compile(r"<link\b[^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"][^>]*\brel\s*=\s*['\"]stylesheet['\"]|<link\b[^>]*\brel\s*=\s*['\"]stylesheet['\"][^>]*\bhref\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
HTML_FORM_ACTION_RE = re.compile(r"<form\b[^>]*\baction\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
HTML_CLASS_RE = re.compile(r"\bclass\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
SQL_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE|CREATE\s+TABLE|ALTER\s+TABLE|DELETE\s+FROM)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?",
    re.IGNORECASE,
)


@dataclass
class SymbolRef:
    name: str
    kind: str
    path: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "path": self.path, "line": self.line}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SymbolRef:
        return cls(name=str(data["name"]), kind=str(data["kind"]), path=str(data["path"]), line=int(data["line"]))


@dataclass
class FileNode:
    path: str
    language: str
    symbols: list[SymbolRef] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    sql_tables: list[str] = field(default_factory=list)
    referenced_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "includes": list(self.includes),
            "endpoints": list(self.endpoints),
            "sql_tables": list(self.sql_tables),
            "referenced_by": list(self.referenced_by),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileNode:
        return cls(
            path=str(data["path"]),
            language=str(data["language"]),
            symbols=[SymbolRef.from_dict(item) for item in data.get("symbols", [])],
            includes=[str(item) for item in data.get("includes", [])],
            endpoints=[str(item) for item in data.get("endpoints", [])],
            sql_tables=[str(item) for item in data.get("sql_tables", [])],
            referenced_by=[str(item) for item in data.get("referenced_by", [])],
        )


@dataclass
class RepoMap:
    nodes: dict[str, FileNode]
    relations: dict[str, str]
    generated_at: float
    truncated: bool = False

    def summary(self, limit: int = 40) -> str:
        lines = [
            f"files: {len(self.nodes)}",
            f"relations: {sum(1 for value in self.relations.values() if value != REL_INDEPENDENT)} relevant of {len(self.relations)}",
        ]
        if self.truncated:
            lines.append("truncated: true")
        dependent = sorted(key for key, value in self.relations.items() if value == REL_DEPENDENT)
        unknown = sorted(key for key, value in self.relations.items() if value == REL_UNKNOWN)
        for key in dependent[:limit]:
            lines.append(f"- dependent: {key}")
        remaining = max(0, limit - len(dependent[:limit]))
        for key in unknown[:remaining]:
            lines.append(f"- unknown: {key}")
        return "\n".join(lines)

    def related(self, path: str, depth: int = 2) -> list[str]:
        start = Path(path).as_posix()
        if start not in self.nodes or depth < 1:
            return []
        seen = {start}
        frontier = {start}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for key, relation in self.relations.items():
                if relation == REL_INDEPENDENT or " -> " not in key:
                    continue
                left, right = key.split(" -> ", 1)
                if left in frontier and right not in seen:
                    next_frontier.add(right)
                if right in frontier and left not in seen:
                    next_frontier.add(left)
            seen.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        return sorted(seen - {start})

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {path: node.to_dict() for path, node in sorted(self.nodes.items())},
            "relations": dict(sorted(self.relations.items())),
            "generated_at": self.generated_at,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepoMap:
        return cls(
            nodes={path: FileNode.from_dict(node) for path, node in data.get("nodes", {}).items()},
            relations={str(key): str(value) for key, value in data.get("relations", {}).items()},
            generated_at=float(data.get("generated_at", 0)),
            truncated=bool(data.get("truncated", False)),
        )


class RepoMapBuilder:
    def __init__(self, settings, max_files: int = 400, max_bytes: int = 2_000_000):
        self.settings = settings
        self.root: Path = settings.root
        self.max_files = max_files
        self.max_bytes = max_bytes

    def build(self) -> RepoMap:
        from .file_context import allowed_files

        nodes: dict[str, FileNode] = {}
        truncated = False
        total_bytes = 0
        for rel in allowed_files(self.settings):
            if len(nodes) >= self.max_files or total_bytes >= self.max_bytes:
                truncated = True
                break
            if _has_skipped_part(rel):
                continue
            path = (self.root / rel).resolve()
            try:
                path.relative_to(self.root.resolve())
            except ValueError:
                continue
            if not path.is_file() or path.is_symlink():
                continue
            try:
                size = path.stat().st_size
                raw = path.read_bytes()[:MAX_FILE_BYTES]
            except OSError:
                continue
            total_bytes += min(size, MAX_FILE_BYTES)
            if size > MAX_FILE_BYTES:
                truncated = True
            text = raw.decode("utf-8", errors="replace")
            lines = text.splitlines()
            if len(lines) > MAX_FILE_LINES:
                lines = lines[:MAX_FILE_LINES]
                text = "\n".join(lines)
                truncated = True
            nodes[rel] = self._parse_file(rel, text)
        relations = self._relations(nodes)
        self._fill_references(nodes, relations)
        return RepoMap(nodes=nodes, relations=relations, generated_at=time.time(), truncated=truncated)

    def cache_path(self) -> Path:
        return self.settings.data_dir / "repo-map.json"

    def load_cached(self) -> RepoMap | None:
        path = self.cache_path()
        if not path.is_file():
            return None
        try:
            repo_map = RepoMap.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
        if repo_map.generated_at < self._max_allowed_mtime(repo_map.nodes):
            return None
        return repo_map

    def save(self, repo_map: RepoMap) -> Path:
        path = self.cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(repo_map.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        path.write_text(text + "\n", encoding="utf-8", newline="\n")
        return path

    def _parse_file(self, rel: str, text: str) -> FileNode:
        language = LANGUAGE_BY_SUFFIX.get(Path(rel).suffix.lower(), "other")
        node = FileNode(path=rel, language=language)
        if language == "php":
            self._parse_symbols(node, text, PHP_FUNCTION_RE, "function")
            self._parse_symbols(node, text, PHP_CLASS_RE, "class")
            self._parse_symbols(node, text, PHP_CONST_RE, "const")
            node.includes.extend(_unique(match.group(1) for match in PHP_INCLUDE_RE.finditer(text)))
            node.symbols.extend(
                SymbolRef(name=f"request:{match.group(1)}", kind="request-param", path=rel, line=_line_for(text, match.group(0)))
                for match in PHP_SUPERGLOBAL_RE.finditer(text)
            )
            self._parse_sql_tables(node, text)
            self._parse_markup_refs(node, text)
        elif language == "js":
            self._parse_symbols(node, text, JS_FUNCTION_RE, "function")
            self._parse_symbols(node, text, JS_CONST_FUNCTION_RE, "function")
            node.includes.extend(_unique(match.group(1) for match in JS_IMPORT_RE.finditer(text)))
            node.includes.extend(_unique(match.group(1) for match in JS_DYNAMIC_IMPORT_RE.finditer(text)))
            node.endpoints.extend(_unique(match.group(1) for match in JS_ENDPOINT_RE.finditer(text)))
            for endpoint in node.endpoints:
                node.symbols.append(SymbolRef(name=endpoint, kind="endpoint", path=rel, line=_line_for(text, endpoint)))
            for match in JS_SELECTOR_RE.finditer(text):
                for class_name in _selector_classes(match.group(1)):
                    node.symbols.append(SymbolRef(name=f".{class_name}", kind="css-class-ref", path=rel, line=_line_for(text, match.group(0))))
        elif language == "css":
            node.includes.extend(_unique(match.group(1) for match in CSS_IMPORT_RE.finditer(text)))
            for match in CSS_CLASS_RE.finditer(text):
                node.symbols.append(SymbolRef(name=f".{match.group(1)}", kind="css-class", path=rel, line=_line_for(text, match.group(0))))
        elif language == "html":
            self._parse_markup_refs(node, text)
        elif language == "sql":
            self._parse_sql_tables(node, text)
        return node

    def _parse_symbols(self, node: FileNode, text: str, pattern: re.Pattern[str], kind: str) -> None:
        for match in pattern.finditer(text):
            node.symbols.append(SymbolRef(name=match.group(1), kind=kind, path=node.path, line=_line_for(text, match.group(0))))

    def _parse_sql_tables(self, node: FileNode, text: str) -> None:
        node.sql_tables.extend(_unique(match.group(1) for match in SQL_TABLE_RE.finditer(text)))
        for table in node.sql_tables:
            node.symbols.append(SymbolRef(name=f"table:{table.lower()}", kind="sql-table", path=node.path, line=_line_for(text, table)))

    def _parse_markup_refs(self, node: FileNode, text: str) -> None:
        node.includes.extend(_unique(HTML_SCRIPT_RE.findall(text)))
        stylesheet_refs = []
        for left, right in HTML_STYLESHEET_RE.findall(text):
            stylesheet_refs.append(left or right)
        node.includes.extend(_unique(stylesheet_refs))
        node.endpoints.extend(_unique(match.group(1) for match in HTML_FORM_ACTION_RE.finditer(text)))
        for match in HTML_CLASS_RE.finditer(text):
            for class_name in match.group(1).split():
                node.symbols.append(SymbolRef(name=f".{class_name}", kind="css-class-ref", path=node.path, line=_line_for(text, match.group(0))))

    def _relations(self, nodes: dict[str, FileNode]) -> dict[str, str]:
        relations: dict[str, str] = {}
        paths = sorted(nodes)
        for index, left in enumerate(paths):
            for right in paths[index + 1:]:
                relation = self._relation(nodes[left], nodes[right], set(paths))
                relations[f"{left} -> {right}"] = relation
        return relations

    def _relation(self, left: FileNode, right: FileNode, all_paths: set[str]) -> str:
        if _explicitly_references(left, right, all_paths) or _explicitly_references(right, left, all_paths):
            return REL_DEPENDENT
        if _shared_symbol_names(left, right) or _endpoint_matches(left, right) or _endpoint_matches(right, left):
            return REL_UNKNOWN
        return REL_INDEPENDENT

    def _fill_references(self, nodes: dict[str, FileNode], relations: dict[str, str]) -> None:
        for key, relation in relations.items():
            if relation != REL_DEPENDENT:
                continue
            left, right = key.split(" -> ", 1)
            if _explicitly_references(nodes[left], nodes[right], set(nodes)):
                nodes[right].referenced_by.append(left)
            if _explicitly_references(nodes[right], nodes[left], set(nodes)):
                nodes[left].referenced_by.append(right)
        for node in nodes.values():
            node.referenced_by = sorted(set(node.referenced_by))

    def _max_allowed_mtime(self, nodes: dict[str, FileNode]) -> float:
        newest = 0.0
        for rel in nodes:
            path = self.root / rel
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                return time.time()
        return newest


def _explicitly_references(source: FileNode, target: FileNode, all_paths: set[str]) -> bool:
    return (
        any(_resolve_reference(source.path, item, all_paths) == target.path for item in source.includes)
        or _endpoint_matches(source, target)
        or _sql_table_matches(source, target)
    )


def _endpoint_matches(source: FileNode, target: FileNode) -> bool:
    target_path = _clean_ref(target.path).lower()
    target_name = Path(target_path).name
    for endpoint in source.endpoints:
        cleaned = _clean_ref(endpoint).lower()
        if cleaned == target_path or cleaned.endswith("/" + target_path):
            return True
        if target_name and (cleaned.endswith("/" + target_name) or cleaned == target_name):
            return True
    return False


def _sql_table_matches(source: FileNode, target: FileNode) -> bool:
    if not source.sql_tables or target.language != "sql":
        return False
    source_tables = {table.lower() for table in source.sql_tables}
    target_tables = {table.lower() for table in target.sql_tables}
    return bool(source_tables & target_tables)


def _resolve_reference(source: str, reference: str, all_paths: set[str]) -> str | None:
    normalized = _clean_ref(reference)
    if normalized in all_paths:
        return normalized
    relative = (Path(source).parent / normalized).as_posix()
    if relative in all_paths:
        return relative
    matches = sorted(path for path in all_paths if path.endswith("/" + normalized) or Path(path).name == normalized)
    return matches[0] if len(matches) == 1 else None


def _shared_symbol_names(left: FileNode, right: FileNode) -> bool:
    left_names = {symbol.name.lower() for symbol in left.symbols if symbol.kind != "endpoint"}
    right_names = {symbol.name.lower() for symbol in right.symbols if symbol.kind != "endpoint"}
    return bool(left_names & right_names)


def _line_for(text: str, needle: str) -> int:
    index = text.find(needle)
    if index < 0:
        return 1
    return text.count("\n", 0, index) + 1


def _unique(items) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _has_skipped_part(rel: str) -> bool:
    return any(part in SKIPPED_DIRS for part in Path(rel).parts)


def _clean_ref(reference: str) -> str:
    value = reference.strip()
    value = value.split("#", 1)[0].split("?", 1)[0]
    if value.startswith(("./", "/")):
        value = value.lstrip("./")
    return Path(value).as_posix()


def _selector_classes(selector: str) -> list[str]:
    if selector.startswith(".") and " " not in selector and "#" not in selector:
        return [selector[1:]]
    return re.findall(r"\.([A-Za-z_-][A-Za-z0-9_-]*)", selector)
