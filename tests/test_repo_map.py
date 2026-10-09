from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from hybrid.context import ContextBuilder
from hybrid.context.repo_map import RepoMapBuilder


def settings_for(root: Path, allowed: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        data_dir=root / ".hybrid",
        raw={
            "context": {
                "allowed_files": allowed,
                "max_context_chars": 24000,
                "max_file_chars": 12000,
            },
            "ai_stack": {
                "root": "ai-stack",
                "project_context": "PROJECT_CONTEXT.md",
                "skills_dir": "skills",
                "design_dir": "design",
                "profiles_dir": "profiles",
            },
        },
    )


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def relation(repo_map, left: str, right: str) -> str:
    key = f"{left} -> {right}" if left < right else f"{right} -> {left}"
    return repo_map.relations[key]


def test_php_include_marks_files_dependent(tmp_path: Path):
    write(tmp_path, "index.php", '<?php include "lib/a.php"; function home() {}\n')
    write(tmp_path, "lib/a.php", "<?php function helper() {}\n")

    repo_map = RepoMapBuilder(settings_for(tmp_path, ["index.php", "lib/a.php"])).build()

    assert relation(repo_map, "index.php", "lib/a.php") == "dependent"
    assert repo_map.nodes["lib/a.php"].referenced_by == ["index.php"]


def test_js_ajax_endpoint_matches_php_file_by_name(tmp_path: Path):
    write(tmp_path, "assets/app.js", 'function load(){ return fetch("/ajax/inventory.php"); }\n')
    write(tmp_path, "ajax/inventory.php", "<?php function inventory() {}\n")

    repo_map = RepoMapBuilder(settings_for(tmp_path, ["assets/app.js", "ajax/inventory.php"])).build()

    assert relation(repo_map, "assets/app.js", "ajax/inventory.php") == "dependent"


def test_inventory_flow_links_html_assets_endpoint_and_schema(tmp_path: Path):
    write(
        tmp_path,
        "index.php",
        """<?php require_once "lib/bootstrap.php"; ?>
<link rel="stylesheet" href="assets/inventory.css">
<script src="assets/inventory.js"></script>
<main class="inventory-grid"></main>
""",
    )
    write(tmp_path, "lib/bootstrap.php", "<?php function db() {}\n")
    write(tmp_path, "assets/inventory.css", ".inventory-grid { display: grid; }\n")
    write(tmp_path, "assets/inventory.js", 'export function load(){ return fetch("/ajax/inventory.php?action=list"); }\n')
    write(tmp_path, "ajax/inventory.php", "<?php $rows = $db->query('SELECT * FROM inventory_items');\n")
    write(tmp_path, "schema.sql", "CREATE TABLE inventory_items (id INT PRIMARY KEY);\n")

    repo_map = RepoMapBuilder(
        settings_for(
            tmp_path,
            [
                "index.php",
                "lib/bootstrap.php",
                "assets/inventory.css",
                "assets/inventory.js",
                "ajax/inventory.php",
                "schema.sql",
            ],
        )
    ).build()

    assert relation(repo_map, "index.php", "lib/bootstrap.php") == "dependent"
    assert relation(repo_map, "index.php", "assets/inventory.css") == "dependent"
    assert relation(repo_map, "index.php", "assets/inventory.js") == "dependent"
    assert relation(repo_map, "assets/inventory.js", "ajax/inventory.php") == "dependent"
    assert relation(repo_map, "ajax/inventory.php", "schema.sql") == "dependent"
    assert set(repo_map.related("assets/inventory.js", depth=2)) == {
        "ajax/inventory.php",
        "assets/inventory.css",
        "index.php",
        "lib/bootstrap.php",
        "schema.sql",
    }


def test_js_imports_and_html_forms_are_dependencies(tmp_path: Path):
    write(tmp_path, "assets/app.js", 'import { openInventory } from "./inventory.js";\n')
    write(tmp_path, "assets/inventory.js", "export function openInventory() {}\n")
    write(tmp_path, "inventory.html", '<form action="/ajax/inventory.php" class="inventory-form"></form>\n')
    write(tmp_path, "ajax/inventory.php", "<?php echo '{}';\n")

    repo_map = RepoMapBuilder(
        settings_for(tmp_path, ["assets/app.js", "assets/inventory.js", "inventory.html", "ajax/inventory.php"])
    ).build()

    assert relation(repo_map, "assets/app.js", "assets/inventory.js") == "dependent"
    assert relation(repo_map, "inventory.html", "ajax/inventory.php") == "dependent"


def test_files_without_shared_symbols_are_independent(tmp_path: Path):
    write(tmp_path, "a.php", "<?php function alpha_unique() {}\n")
    write(tmp_path, "b.php", "<?php function beta_unique() {}\n")

    repo_map = RepoMapBuilder(settings_for(tmp_path, ["a.php", "b.php"])).build()

    assert relation(repo_map, "a.php", "b.php") == "independent"


def test_related_keeps_unknown_and_returns_transitive_links(tmp_path: Path):
    write(tmp_path, "a.php", '<?php include "b.php"; function shared_name() {}\n')
    write(tmp_path, "b.php", "<?php function b_only() {}\n")
    write(tmp_path, "c.php", "<?php function shared_name() {}\n")

    repo_map = RepoMapBuilder(settings_for(tmp_path, ["a.php", "b.php", "c.php"])).build()

    assert relation(repo_map, "a.php", "c.php") == "unknown"
    assert repo_map.related("b.php", depth=2) == ["a.php", "c.php"]


def test_heavy_directories_are_not_indexed(tmp_path: Path):
    write(tmp_path, "app.php", "<?php function app() {}\n")
    write(tmp_path, "vendor/lib.php", "<?php function app() {}\n")
    write(tmp_path, "node_modules/pkg/index.js", "function app() {}\n")

    repo_map = RepoMapBuilder(settings_for(tmp_path, ["app.php", "vendor/lib.php", "node_modules/pkg/index.js"])).build()

    assert sorted(repo_map.nodes) == ["app.php"]


def test_large_file_is_truncated_and_does_not_fail_build(tmp_path: Path):
    big = "<?php function early_symbol() {}\n" + ("// filler\n" * 40000)
    write(tmp_path, "big.php", big)

    repo_map = RepoMapBuilder(settings_for(tmp_path, ["big.php"])).build()

    assert repo_map.truncated is True
    assert "big.php" in repo_map.nodes
    assert repo_map.nodes["big.php"].symbols[0].name == "early_symbol"


def test_cache_is_reused_and_invalidated_when_file_changes(tmp_path: Path):
    write(tmp_path, "a.php", "<?php function alpha() {}\n")
    settings = settings_for(tmp_path, ["a.php"])
    builder = RepoMapBuilder(settings)
    first = builder.build()
    builder.save(first)

    cached = builder.load_cached()
    assert cached is not None
    assert cached.generated_at == first.generated_at

    future = first.generated_at + 10
    (tmp_path / "a.php").touch()
    import os

    os.utime(tmp_path / "a.php", (future, future))
    assert builder.load_cached() is None


def test_context_pack_summary_is_empty_without_repo_map(tmp_path: Path):
    write(tmp_path, "app.js", "function app() {}\n")
    task = SimpleNamespace(task_id="T1", description="update js")

    pack = ContextBuilder(settings_for(tmp_path, ["app.js"])).build(task, "frontend")

    assert pack.repo_map_summary == ""
    assert "# REPO MAP" not in pack.prompt_text()


def test_context_builder_uses_repo_map_without_widening_allowed_files(tmp_path: Path):
    write(tmp_path, "index.php", '<?php include "hidden.php"; function index_page() {}\n')
    write(tmp_path, "allowed.js", 'fetch("index.php");\n')
    write(tmp_path, "hidden.php", "<?php function hidden() {}\n")
    settings = settings_for(tmp_path, ["index.php", "allowed.js"])
    repo_map = RepoMapBuilder(settings).build()
    task = SimpleNamespace(task_id="T1", description="update backend php")

    pack = ContextBuilder(settings, repo_map=repo_map).build(task, "backend-php")

    assert pack.used_files() == ["index.php", "allowed.js"]
    assert "hidden.php" not in pack.used_files()
    assert "# REPO MAP" in pack.prompt_text()
