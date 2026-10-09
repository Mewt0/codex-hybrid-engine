from __future__ import annotations

from pathlib import Path

import pytest

from hybrid.config import load_settings
from hybrid.context import PROFILES, ContextBuilder, SkillLibrary, choose_profile
from test_engine import project


def test_skills_are_available_for_a_project_without_its_own_ai_stack(project: Path):
    """A target project without ai-stack/ still gets the engine skills."""
    settings = load_settings(project)
    builder = ContextBuilder(settings)
    assert builder.stack_dir.name == "ai-stack"
    assert builder.skills_dir.is_dir()
    assert builder.skills(), "no skills loaded for an external project"


def test_project_local_ai_stack_wins_over_engine_library(project: Path):
    local = project / "ai-stack" / "skills" / "local-only"
    local.mkdir(parents=True)
    (local / "SKILL.md").write_text(
        "---\nname: local-only\ndescription: project specific\ntriggers: [local]\n---\n# Local\n\nProject rules.\n",
        encoding="utf-8",
    )
    builder = ContextBuilder(load_settings(project))
    assert builder.stack_dir == (project / "ai-stack").resolve()
    assert "local-only" in builder.skills()


def test_pack_selects_only_profile_skills(project: Path):
    settings = load_settings(project)
    builder = ContextBuilder(settings)
    task = type("T", (), {"task_id": "TASK-X", "description": "поправь css кнопки"})()
    pack = builder.build(task, "frontend")
    assert pack.profile == "frontend"
    assert set(pack.skill_names()) == set(PROFILES["frontend"])


def test_pack_for_backend_profile_excludes_design(project: Path):
    settings = load_settings(project)
    pack = ContextBuilder(settings).build(
        type("T", (), {"task_id": "TASK-Y", "description": "исправь php endpoint"}) (),
        "backend-php",
    )
    assert "design" not in pack.sections
    assert "project_context" in pack.sections
    assert set(pack.skill_names()) == set(PROFILES["backend-php"])


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown profile"):
        choose_profile("task", "nope")


def test_skill_loader_ignores_directories_without_skill_md(project: Path):
    empty = project / "ai-stack" / "skills" / "no-skill-file"
    empty.mkdir(parents=True)
    library = SkillLibrary(project / "ai-stack" / "skills")
    assert "no-skill-file" not in library.load()
