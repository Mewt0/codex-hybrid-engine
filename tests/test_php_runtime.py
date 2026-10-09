"""Regressions for PHP runtime resolution.

The bug these guard against: the quality gate linted PHP with "the newest build
installed" while the functional test used a different, hard-coded runtime. On a
project migrating PHP versions that makes a green check meaningless — a file can
pass the gate and fail on the runtime the site actually serves.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hybrid import php_runtime
from hybrid.php_runtime import available_builds, php_binary, resolve_php
from hybrid.quality.checks import run_quality


@pytest.fixture()
def fake_ospanel(tmp_path: Path, monkeypatch) -> Path:
    """A synthetic OSPanel tree with three PHP builds."""
    root = tmp_path / "modules" / "php"
    for name in ("PHP_7.4", "PHP_8.1", "PHP_8.5.11"):
        build = root / name
        build.mkdir(parents=True)
        (build / "php.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(php_runtime, "OSPANEL_ROOTS", (root,))
    monkeypatch.delenv("HYBRID_PHP_BIN", raising=False)
    monkeypatch.setattr(php_runtime.shutil, "which", lambda name: None)
    return root


def test_available_builds_are_version_sorted(fake_ospanel: Path):
    versions = [version for version, _ in available_builds()]
    assert versions == [(7, 4, 0), (8, 1, 0), (8, 5, 11)]


def test_composer_floor_selects_the_lowest_satisfying_build(fake_ospanel: Path, tmp_path: Path):
    """`>=8.1` promises support for 8.1, so lint against 8.1, not the newest."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "composer.json").write_text(json.dumps({"require": {"php": ">=8.1"}}), encoding="utf-8")
    runtime = resolve_php(project)
    assert runtime is not None
    assert runtime.version == (8, 1, 0)
    assert "composer.json" in runtime.source


def test_composer_requiring_newer_php_picks_that_build(fake_ospanel: Path, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "composer.json").write_text(json.dumps({"require": {"php": ">=8.3"}}), encoding="utf-8")
    runtime = resolve_php(project)
    assert runtime is not None
    assert runtime.version == (8, 5, 11)


def test_php_version_marker_wins_over_composer(fake_ospanel: Path, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "composer.json").write_text(json.dumps({"require": {"php": ">=8.1"}}), encoding="utf-8")
    (project / ".php-version").write_text("8.5.11\n", encoding="utf-8")
    runtime = resolve_php(project)
    assert runtime is not None
    assert runtime.version == (8, 5, 11)
    assert ".php-version" in runtime.source


def test_explicit_override_wins_everything(fake_ospanel: Path, tmp_path: Path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".php-version").write_text("8.1\n", encoding="utf-8")
    pinned = fake_ospanel / "PHP_7.4" / "php.exe"
    monkeypatch.setenv("HYBRID_PHP_BIN", str(pinned))
    runtime = resolve_php(project)
    assert runtime is not None
    assert runtime.path == str(pinned)
    assert runtime.source == "HYBRID_PHP_BIN"


def test_without_a_constraint_the_newest_build_is_used_and_labelled(fake_ospanel: Path, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    runtime = resolve_php(project)
    assert runtime is not None
    assert runtime.version == (8, 5, 11)
    # The fallback must be honest that no project constraint decided this.
    assert "no project constraint" in runtime.source


def test_malformed_composer_json_does_not_crash(fake_ospanel: Path, tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "composer.json").write_text("{ not json", encoding="utf-8")
    runtime = resolve_php(project)
    assert runtime is not None  # falls back rather than raising


def test_php_binary_compatibility_helper(fake_ospanel: Path, tmp_path: Path):
    assert php_binary(tmp_path) is not None


def test_missing_php_is_reported_as_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(php_runtime, "OSPANEL_ROOTS", (tmp_path / "nope",))
    monkeypatch.setattr(php_runtime.shutil, "which", lambda name: None)
    monkeypatch.delenv("HYBRID_PHP_BIN", raising=False)
    assert resolve_php(tmp_path) is None
    assert php_binary(tmp_path) is None


def test_quality_check_records_which_php_linted(tmp_path: Path, monkeypatch):
    """A bare PASS is ambiguous during a version migration; the version must show."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "index.php").write_text("<?php echo 'ok';\n", encoding="utf-8")

    fake = tmp_path / "php.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("HYBRID_PHP_BIN", str(fake))

    recorded: list[list[str]] = []

    def fake_run(args, cwd, name):
        recorded.append(list(args))
        from hybrid.quality.checks import CheckResult

        return CheckResult(name, "PASS", "No syntax errors detected")

    monkeypatch.setattr("hybrid.quality.checks._run", fake_run)
    results = run_quality(project, ["index.php"])
    php_results = [r for r in results if r.name.startswith("PHP Syntax")]
    assert php_results, "expected a PHP syntax result"
    assert "HYBRID_PHP_BIN" in php_results[0].detail
    # And it must have actually invoked the pinned binary, not another one.
    php_calls = [call for call in recorded if call[0] == str(fake)]
    assert php_calls, f"pinned PHP was not invoked; calls={recorded}"
    assert php_calls[0][1:3] == ["-l", "index.php"]
    # No other PHP build may have been used for linting.
    other_php = [call for call in recorded if "php" in Path(call[0]).name.lower() and call[0] != str(fake)]
    assert not other_php, f"a different PHP was used: {other_php}"
