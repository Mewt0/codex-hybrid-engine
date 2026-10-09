from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import copy
import os
import yaml


DEFAULT_CONFIG = {
    "providers": {
        "codex": {"enabled": True, "timeout_seconds": 300, "command": "codex"},
        "groq": {
            "enabled": True,
            "base_url": "https://api.groq.com/openai/v1",
            "small_model": "qwen/qwen3.8-27b",
            "review_model": "openai/gpt-oss-120b",
            "timeout_seconds": 60,
        },
        "openrouter": {
            "enabled": False,
            "base_url": "https://openrouter.ai/api/v1",
            "small_model": "openai/gpt-oss-120b:free",
            "review_model": "openai/gpt-oss-120b:free",
            "timeout_seconds": 60,
        },
    },
    "deepseek_harness": {"enabled": False, "max_parallel_agents": 2, "timeout_seconds": 180},
    "budget": {"allow_paid_api": False, "max_retries": 1, "max_parallel_agents": 1},
    "architecture": {
        "allow_new_dependencies": False,
        "max_files_changed": 5,
        "forbidden_paths": [".env", "config/secrets/*", "tests/protected/*"],
    },
    "quality": {"auto_merge": False, "require_approval": True},
    "visual": {
        "command": None,
        "timeout_seconds": 60,
        "agent_browser_command": "agent-browser",
    },
    "browser_session": {
        "port": 9333,
        "profile_dir": None,
        "command": None,
        "headless": False,
        "start_url": "https://chatgpt.com/",
    },
    "context": {
        "allowed_files": [],
        "max_context_chars": 24000,
        "max_file_chars": 12000,
        "max_response_chars": 30000,
        "max_pack_chars": 80000,
    },
    "ai_stack": {
        "root": "ai-stack",
        "project_context": "PROJECT_CONTEXT.md",
        "skills_dir": "skills",
        "design_dir": "design",
        "profiles_dir": "profiles",
        "stack_description": (
            "legacy PHP backend, plain JavaScript with fetch/AJAX, MySQL, HTML and CSS. "
            "No framework, no build step, no TypeScript."
        ),
    },
}

MANDATORY_FORBIDDEN_PATHS = [".env", ".env.*", "config/secrets/*", "tests/protected/*"]


@dataclass
class Settings:
    root: Path
    data_dir: Path
    raw: dict = field(default_factory=lambda: copy.deepcopy(DEFAULT_CONFIG))
    sources: dict = field(default_factory=dict)

    @property
    def state_file(self) -> Path:
        return self.data_dir / "tasks.json"


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


TRUSTED_PROVIDER_FIELDS = {
    "codex": {"enabled", "timeout_seconds", "sandbox"},
    "groq": {"enabled", "small_model", "review_model", "timeout_seconds"},
    "openrouter": {"enabled", "small_model", "review_model", "timeout_seconds"},
}

# Fields a project may never set at all, not even to a "safe-looking" value.
#
# Sandbox controls are trusted-user-only: a project settings file may not weaken
# the boundary. `windows_sandbox=unelevated` was measured to allow writes outside
# the workspace; `sandbox` selects Codex CLI's sandbox mode directly.
PROJECT_FORBIDDEN_PROVIDER_FIELDS = {
    "codex": {"windows_sandbox", "sandbox"},
}
TRUSTED_BROWSER_SESSION_FIELDS = {"command", "profile_dir"}


def _filtered_project_config(loaded: dict) -> tuple[dict, dict]:
    if not isinstance(loaded, dict):
        raise ValueError("settings.yaml must contain a mapping")
    filtered = copy.deepcopy(loaded)
    sources: dict = {"ignored_project_fields": []}
    providers = dict(filtered.get("providers", {}) or {})
    for name, cfg in list(providers.items()):
        if not isinstance(cfg, dict):
            continue
        allowed = TRUSTED_PROVIDER_FIELDS.get(name)
        forbidden = PROJECT_FORBIDDEN_PROVIDER_FIELDS.get(name, set())
        if allowed is None:
            continue
        clean = {}
        for key, value in cfg.items():
            if key in forbidden:
                sources["ignored_project_fields"].append(f"providers.{name}.{key}")
            elif key in allowed:
                clean[key] = value
            else:
                sources["ignored_project_fields"].append(f"providers.{name}.{key}")
        providers[name] = clean
    if providers:
        filtered["providers"] = providers
    browser_session = dict(filtered.get("browser_session", {}) or {})
    if browser_session:
        for key in TRUSTED_BROWSER_SESSION_FIELDS:
            if key in browser_session:
                browser_session.pop(key)
                sources["ignored_project_fields"].append(f"browser_session.{key}")
        filtered["browser_session"] = browser_session
    context = dict(filtered.get("context", {}) or {})
    if "allowed_files" in context:
        sources["project_context_allowed_files"] = list(context.get("allowed_files") or [])
        context.pop("allowed_files", None)
        filtered["context"] = context
    return filtered, sources


def _trusted_user_config_path() -> Path:
    env_path = os.environ.get("HYBRID_USER_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "codex-hybrid-engine" / "settings.yaml"


def load_settings(project_dir: Path) -> Settings:
    project_dir = project_dir.resolve()
    config_path = project_dir / "config" / "settings.yaml"
    raw = copy.deepcopy(DEFAULT_CONFIG)
    sources: dict = {
        "providers.codex.command": "default",
        "providers.groq.base_url": "default",
        "providers.openrouter.base_url": "default",
        "trusted_user_config": str(_trusted_user_config_path()),
    }
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        filtered, project_sources = _filtered_project_config(loaded)
        raw = deep_merge(raw, filtered)
        sources.update(project_sources)
    user_config = _trusted_user_config_path()
    user_loaded: dict = {}
    if user_config.exists():
        loaded = yaml.safe_load(user_config.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("trusted user settings must contain a mapping")
        user_loaded = loaded
        raw = deep_merge(raw, loaded)
        codex_user_config = loaded.get("providers", {}).get("codex", {})
        if codex_user_config.get("command"):
            sources["providers.codex.command"] = "trusted_user"
        if "sandbox" in codex_user_config:
            sources["providers.codex.sandbox"] = "trusted_user"
        if loaded.get("providers", {}).get("groq", {}).get("base_url"):
            sources["providers.groq.base_url"] = "trusted_user"
        if loaded.get("providers", {}).get("openrouter", {}).get("base_url"):
            sources["providers.openrouter.base_url"] = "trusted_user"
    _strip_project_only_forbidden_fields(raw, user_loaded, sources)
    _merge_security_rules(raw, sources)
    data_dir = Path(os.environ.get("HYBRID_DATA_DIR", project_dir / ".hybrid")).resolve()
    _validate_settings(raw)
    return Settings(root=project_dir, data_dir=data_dir, raw=raw, sources=sources)


def _strip_project_only_forbidden_fields(raw: dict, user_loaded: dict, sources: dict) -> None:
    """Remove forbidden provider fields that came only from project config.

    `_filtered_project_config` already refuses to copy them, but a project value
    could still survive through key aliasing, so the guarantee is enforced once
    more against the merged result: if the trusted user config did not set the
    field, it does not exist.
    """
    for provider_name, forbidden in PROJECT_FORBIDDEN_PROVIDER_FIELDS.items():
        provider = raw.get("providers", {}).get(provider_name)
        if not isinstance(provider, dict):
            continue
        user_provider = user_loaded.get("providers", {}).get(provider_name, {}) if isinstance(user_loaded, dict) else {}
        if not isinstance(user_provider, dict):
            user_provider = {}
        user_keys = {key.replace("-", "_") for key in user_provider}
        for key in list(provider):
            if key not in forbidden:
                continue
            if key.replace("-", "_") in user_keys:
                sources[f"providers.{provider_name}.{key}"] = "trusted_user"
                continue
            provider.pop(key)
            entry = f"providers.{provider_name}.{key}"
            if entry not in sources["ignored_project_fields"]:
                sources["ignored_project_fields"].append(entry)


def _merge_security_rules(raw: dict, sources: dict) -> None:
    architecture = raw.setdefault("architecture", {})
    configured = architecture.get("forbidden_paths", [])
    if not isinstance(configured, list):
        configured = []
    architecture["forbidden_paths"] = list(dict.fromkeys([*MANDATORY_FORBIDDEN_PATHS, *configured]))

    project_allowed = sources.get("project_context_allowed_files")
    if project_allowed is not None:
        trusted_allowed = raw.setdefault("context", {}).get("allowed_files", [])
        if not isinstance(trusted_allowed, list):
            trusted_allowed = []
        raw["context"]["allowed_files"] = [item for item in trusted_allowed if item in set(project_allowed)]


def _validate_settings(raw: dict) -> None:
    providers = raw.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("providers must be a mapping")
    for provider_name in ("codex", "groq", "openrouter"):
        if not isinstance(providers.get(provider_name), dict):
            raise ValueError(f"providers.{provider_name} must be a mapping")
        enabled = providers[provider_name].get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"providers.{provider_name}.enabled must be boolean")
    deepseek_harness = raw.get("deepseek_harness")
    if not isinstance(deepseek_harness, dict):
        raise ValueError("deepseek_harness must be a mapping")
    enabled = deepseek_harness.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("deepseek_harness.enabled must be boolean")
    for key in ("max_parallel_agents", "timeout_seconds"):
        value = deepseek_harness.get(key, DEFAULT_CONFIG["deepseek_harness"][key])
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"deepseek_harness.{key} must be a positive integer")
    architecture = raw.get("architecture")
    if not isinstance(architecture, dict):
        raise ValueError("architecture must be a mapping")
    forbidden = architecture.get("forbidden_paths", [])
    if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
        raise ValueError("architecture.forbidden_paths must be a list of strings")
    context = raw.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("context must be a mapping")
    allowed = context.get("allowed_files", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise ValueError("context.allowed_files must be a list of strings")
    for limit_name in ("max_context_chars", "max_file_chars", "max_response_chars"):
        limit = context.get(limit_name, DEFAULT_CONFIG["context"][limit_name])
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError(f"context.{limit_name} must be a positive integer")
    ai_stack = raw.get("ai_stack", {})
    if not isinstance(ai_stack, dict):
        raise ValueError("ai_stack must be a mapping")


def write_example_config(path: Path) -> None:
    example = copy.deepcopy(DEFAULT_CONFIG)
    example["providers"]["codex"].pop("command", None)
    example["providers"]["groq"].pop("base_url", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(example, sort_keys=False), encoding="utf-8")

