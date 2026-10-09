"""Phase 8 regressions: provider status must never overstate reality.

The failure mode these guard against is a report that treats "an API key exists"
as "the integration works". Each test pins one honest distinction.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hybrid.config import DEFAULT_CONFIG, load_settings
from hybrid.providers.status import (
    ProviderStatus,
    browser_provider_statuses,
    format_statuses,
    provider_statuses,
)


@pytest.fixture()
def project(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("HYBRID_USER_CONFIG", str(tmp_path / "no-user-config.yaml"))
    monkeypatch.setenv("HYBRID_DATA_DIR", str(root / ".hybrid"))
    return root


def status_by_name(settings, name: str) -> ProviderStatus:
    return next(s for s in provider_statuses(settings) if s.name == name)


def test_configuring_a_key_does_not_prove_a_live_call(project: Path, monkeypatch):
    """A present API key is not evidence that the model answered."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    settings = load_settings(project)
    groq = status_by_name(settings, "groq")
    assert groq.authenticated is True
    assert groq.configured is True
    # The whole point: credentials located, live call never performed.
    assert groq.live_verified is False


def test_missing_key_is_reported_as_error_not_silent(project: Path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings = load_settings(project)
    groq = status_by_name(settings, "groq")
    assert groq.authenticated is False
    assert groq.live_verified is False
    assert "GROQ_API_KEY" in (groq.error or "")


def test_disabled_provider_is_distinguishable_from_a_broken_one(project: Path):
    """openrouter is disabled by default: that is not an error condition."""
    settings = load_settings(project)
    openrouter = status_by_name(settings, "openrouter")
    assert openrouter.disabled is True
    assert openrouter.enabled is False
    assert openrouter.live_verified is False
    assert "DISABLED" in openrouter.summary()


def test_codex_is_never_live_verified_without_a_real_run(project: Path):
    settings = load_settings(project)
    codex = status_by_name(settings, "codex")
    assert codex.kind == "agent"
    assert codex.live_verified is False


def test_codex_login_is_labelled_an_assumption(project: Path):
    settings = load_settings(project)
    codex = status_by_name(settings, "codex")
    if codex.authenticated:
        # Resolving the executable does not prove its login state.
        assert "login" in codex.detail.lower()


def test_mock_is_the_only_provider_live_verified_by_default(project: Path):
    settings = load_settings(project)
    verified = [s.name for s in provider_statuses(settings) if s.live_verified]
    assert verified == ["mock"]


def test_harness_stays_disabled_until_proven(project: Path):
    settings = load_settings(project)
    harness = status_by_name(settings, "deepseek_harness")
    assert harness.disabled is True
    assert harness.live_verified is False


def test_all_six_states_are_representable():
    """The dataclass must be able to express every documented state."""
    states = [
        ProviderStatus("a", "agent", True, True, True, True, False, None),   # live verified
        ProviderStatus("b", "agent", True, True, True, False, False, None),  # authenticated
        ProviderStatus("c", "model", True, True, False, False, False, "no key"),  # error
        ProviderStatus("d", "model", True, False, False, False, True, "disabled"),  # disabled
        ProviderStatus("e", "model", False, True, False, False, False, "missing base_url"),  # not configured
    ]
    summaries = [s.summary() for s in states]
    assert any("LIVE VERIFIED" in s for s in summaries)
    assert any("AUTHENTICATED" in s for s in summaries)
    assert any("ERROR" in s for s in summaries)
    assert any("DISABLED" in s for s in summaries)
    assert any("NOT CONFIGURED" in s for s in summaries)


def test_browser_providers_are_never_live_verified():
    """Web chats require a real conversation; status must not claim one."""
    statuses = browser_provider_statuses()
    assert statuses, "expected at least one browser provider"
    assert all(s.live_verified is False for s in statuses)
    assert all(s.kind == "browser" for s in statuses)
    assert all("live" in s.detail.lower() for s in statuses)


def test_status_is_json_serialisable(project: Path):
    payload = [s.as_dict() for s in provider_statuses(load_settings(project))]
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "live_verified" in encoded
    assert json.loads(encoded)[0]["name"]


def test_format_statuses_prints_every_provider(project: Path):
    statuses = provider_statuses(load_settings(project))
    text = format_statuses(statuses)
    for status in statuses:
        assert status.name in text
    assert "live_verified" in text
