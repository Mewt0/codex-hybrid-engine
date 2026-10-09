"""Site-specific browser automation profiles.

Profiles keep selector and capability differences out of the shared state
machine. DeepSeek selectors stay empty until measured against an accessible,
live page; guesses must never be used to drive a user's browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlparse

from ..browser_state import Selector


@dataclass(frozen=True)
class SiteProfile:
    name: str
    display_name: str
    hostnames: tuple[str, ...]
    new_conversation_url: str
    conversation_url_re: re.Pattern[str]
    selectors: dict[str, tuple[Selector, ...]] = field(default_factory=dict)
    supports_turn_state: bool = False
    supports_effort: bool = False
    supports_mode_tabs: bool = False
    supports_archive: bool = False
    turn_state_attribute: str = ""
    turn_state_done: frozenset[str] = frozenset()
    turn_state_running: frozenset[str] = frozenset()
    role_labels: tuple[str, ...] = ()
    login_wall_re: str = ""
    captcha_re: str = ""
    rate_limit_re: str = ""
    answer_body_join: str = "\n"
    composer_exclude_classes: tuple[str, ...] = ()
    detect_effort: Callable | None = None
    new_conversation: Callable | None = None
    archive_conversation: Callable | None = None

    def __hash__(self) -> int:
        return hash(self.name)


SITES: dict[str, SiteProfile] = {}
_PROVIDER_SITES = {
    "chatgpt_web": "chatgpt",
    "chatgpt": "chatgpt",
    "gpt": "chatgpt",
    "deepseek_web": "deepseek",
    "deepseek": "deepseek",
}


def site_for_provider(provider: str) -> SiteProfile:
    key = (provider or "").strip().lower()
    name = _PROVIDER_SITES.get(key, key)
    try:
        return SITES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown browser site/provider: {provider}") from exc


def site_for_url(url: str) -> SiteProfile | None:
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    return next((profile for profile in SITES.values() if hostname in profile.hostnames), None)


def default_site() -> SiteProfile:
    return SITES["chatgpt"]


from . import chatgpt as _chatgpt
from . import deepseek as _deepseek

SITES.update(chatgpt=_chatgpt.CHATGPT, deepseek=_deepseek.DEEPSEEK)

__all__ = ["Selector", "SiteProfile", "SITES", "default_site", "site_for_provider", "site_for_url"]
