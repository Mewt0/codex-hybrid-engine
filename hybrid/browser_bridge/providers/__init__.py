from __future__ import annotations

from .base import BrowserPrompt, BrowserProvider, BrowserProviderError
from .chatgpt_web import ChatGptWebProvider
from .deepseek_web import DeepSeekWebProvider

PROVIDERS: dict[str, BrowserProvider] = {
    DeepSeekWebProvider.name: DeepSeekWebProvider(),
    ChatGptWebProvider.name: ChatGptWebProvider(),
}

# Short aliases so the CLI stays pleasant: `--provider deepseek`.
ALIASES = {
    "deepseek": DeepSeekWebProvider.name,
    "chatgpt": ChatGptWebProvider.name,
    "gpt": ChatGptWebProvider.name,
}


def get_provider(name: str) -> BrowserProvider:
    key = (name or "").strip().lower()
    key = ALIASES.get(key, key)
    provider = PROVIDERS.get(key)
    if provider is None:
        known = ", ".join(sorted(PROVIDERS))
        raise BrowserProviderError(f"Unknown browser provider: {name}. Known providers: {known}")
    return provider


def provider_names() -> list[str]:
    return sorted(PROVIDERS)


__all__ = [
    "BrowserPrompt",
    "BrowserProvider",
    "BrowserProviderError",
    "ChatGptWebProvider",
    "DeepSeekWebProvider",
    "PROVIDERS",
    "ALIASES",
    "get_provider",
    "provider_names",
]
