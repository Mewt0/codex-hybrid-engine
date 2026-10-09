"""Honest provider status reporting.

The Phase 8 requirement is that a provider's status must distinguish six things
that were previously collapsed into one AVAILABLE/UNAVAILABLE line:

    configured | enabled | authenticated | live_verified | disabled | error

Collapsing them is how a project ends up claiming an integration works when only
a config key was present. The rules encoded here:

* `configured`     - the settings the provider needs are present.
* `enabled`        - trusted config did not disable it.
* `authenticated`  - credentials the provider needs were located. For an agent
                     CLI this means the executable resolves; for an HTTP provider
                     it means the API key env var is set. **A key existing is not
                     proof the model is reachable.**
* `live_verified`  - a real call to the provider succeeded *in this process*.
                     Never inferred from configuration; it stays False until
                     something actually proves it.
* `disabled`       - explicitly turned off.
* `error`          - the concrete reason the provider is not usable.

`live_verified` is deliberately pessimistic: without an explicit successful probe
the answer is False, so a report can never claim a live integration it did not
perform.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path

from .codex import CodexProvider
from .groq import GroqProvider
from .openrouter import OpenRouterProvider

# Agent CLIs authenticate through their own local login state, which this
# function cannot verify without running them. Reporting `authenticated` for a
# resolvable executable is an *assumption*, and it is labelled as one.
AGENT_LOGIN_NOTE = "assumes the CLI's own local login; not verified here"


@dataclass
class ProviderStatus:
    name: str
    kind: str
    configured: bool
    enabled: bool
    authenticated: bool
    live_verified: bool
    disabled: bool
    error: str | None
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        # Order matters: "not configured" is a property of the settings, while
        # "error" is a runtime failure. Reporting an unconfigured provider as a
        # plain error hides the more useful fact that its settings are incomplete.
        if self.disabled:
            state = "DISABLED"
        elif not self.configured:
            state = "NOT CONFIGURED"
        elif self.error:
            state = "ERROR"
        elif self.live_verified:
            state = "LIVE VERIFIED"
        elif self.authenticated:
            state = "AUTHENTICATED (not live verified)"
        else:
            state = "NOT AUTHENTICATED"
        return f"{self.name}: {state}"


def _http_provider_status(name: str, config: dict, budget: dict | None = None) -> ProviderStatus:
    if name == "groq":
        provider = GroqProvider(config, budget or {"max_retries": 1, "allow_paid_api": False})
        key_env = "GROQ_API_KEY"
    else:
        provider = OpenRouterProvider(config, budget or {"max_retries": 1, "allow_paid_api": False})
        key_env = "OPENROUTER_API_KEY"

    enabled = config.get("enabled", True) is True
    has_key = bool(os.environ.get(key_env))
    base_url = str(config.get("base_url") or "")
    model = str(config.get("small_model") or "")
    configured = bool(base_url and model)

    error = None
    if not enabled:
        error = "disabled by configuration"
    elif not configured:
        error = "base_url or model is missing"
    elif not has_key:
        # The provider's own message is the source of truth for the wording.
        ok, detail = provider.available()
        error = detail if not ok else f"{key_env} is not set"

    return ProviderStatus(
        name=name,
        kind="model",
        configured=configured,
        enabled=enabled,
        authenticated=has_key,
        live_verified=False,
        disabled=not enabled,
        error=error,
        detail=f"key env: {key_env}; model: {model or 'unset'}",
    )


def _codex_status(config: dict) -> ProviderStatus:
    enabled = config.get("enabled", True) is True
    provider = CodexProvider(config)
    ok, detail = provider.available()
    resolved = None
    if ok:
        try:
            resolved = provider._resolve_command()
        except Exception:  # pragma: no cover - available() already checked
            resolved = None
    if not enabled:
        error = "disabled by configuration"
    elif not ok:
        error = detail
    else:
        error = None
    return ProviderStatus(
        name="codex",
        kind="agent",
        configured=bool(resolved),
        enabled=enabled,
        authenticated=bool(resolved),
        live_verified=False,
        disabled=not enabled,
        error=error,
        detail=f"{resolved or 'unresolved'}; {AGENT_LOGIN_NOTE}",
    )


def _harness_status(config: dict) -> ProviderStatus:
    enabled = config.get("enabled", False) is True
    return ProviderStatus(
        name="deepseek_harness",
        kind="agent",
        configured=enabled,
        enabled=enabled,
        authenticated=False,
        live_verified=False,
        disabled=not enabled,
        error=None if enabled else "disabled by configuration",
        detail="optional integration; stays disabled until its local contract is proven",
    )


def _mock_status() -> ProviderStatus:
    # The mock provider is the one provider that is genuinely verified locally:
    # it is exercised by the E2E suite with no network at all.
    return ProviderStatus(
        name="mock",
        kind="agent",
        configured=True,
        enabled=True,
        authenticated=True,
        live_verified=True,
        disabled=False,
        error=None,
        detail="local provider; verified by the offline E2E suite",
    )


def provider_statuses(settings) -> list[ProviderStatus]:
    providers = settings.raw.get("providers", {})
    budget = settings.raw.get("budget", {})
    statuses = [
        _codex_status(providers.get("codex", {})),
        _http_provider_status("groq", providers.get("groq", {}), budget),
        _http_provider_status("openrouter", providers.get("openrouter", {}), budget),
        _mock_status(),
        _harness_status(settings.raw.get("deepseek_harness", {})),
    ]
    return statuses


def browser_provider_statuses() -> list[ProviderStatus]:
    """Browser providers are manual-relay only.

    They are never `live_verified` here: a web chat answer is only proven by a
    real conversation, which this function does not perform. Reporting
    `LOCAL WORKFLOW VERIFIED` rather than `LIVE VERIFIED` is the requirement.
    """
    from ..browser_bridge.providers import PROVIDERS  # local import: optional deps

    statuses: list[ProviderStatus] = []
    for name in sorted(PROVIDERS):
        statuses.append(
            ProviderStatus(
                name=name,
                kind="browser",
                configured=True,
                enabled=True,
                authenticated=False,
                live_verified=False,
                disabled=False,
                error=None,
                detail="manual relay; requires a live conversation to be called LIVE VERIFIED",
            )
        )
    return statuses


def format_statuses(statuses: list[ProviderStatus]) -> str:
    lines: list[str] = []
    for status in statuses:
        lines.append(status.summary())
        lines.append(f"  kind: {status.kind}")
        lines.append(f"  configured: {status.configured}  enabled: {status.enabled}")
        lines.append(f"  authenticated: {status.authenticated}  live_verified: {status.live_verified}")
        if status.disabled:
            lines.append("  disabled: True")
        if status.error:
            lines.append(f"  error: {status.error}")
        if status.detail:
            lines.append(f"  detail: {status.detail}")
    return "\n".join(lines)
