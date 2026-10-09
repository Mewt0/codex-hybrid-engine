"""DeepSeek web profile.

Selectors are added only after live inspection. The composer has been measured
on the authenticated conversation page; message submission and answer selectors
remain empty, so this profile still fails closed for automation.
"""

from __future__ import annotations

import re

from . import Selector, SiteProfile

DEEPSEEK = SiteProfile(
    name="deepseek",
    display_name="DeepSeek",
    hostnames=("chat.deepseek.com",),
    new_conversation_url="https://chat.deepseek.com/",
    conversation_url_re=re.compile(r"^/a/chat/s/[A-Za-z0-9-]+$"),
    selectors={
        "composer": (
            Selector('textarea[name="search"]', 0.95, "visible DeepSeek message composer, live-verified"),
        ),
    },
    supports_turn_state=False,
    supports_effort=False,
    supports_mode_tabs=False,
    supports_archive=False,
    role_labels=(),
    login_wall_re=r"log in|sign up|войти|зарегистр",
    captcha_re=r"verify you are human|one more step|проверка.*человек|captcha|cloudflare",
    rate_limit_re=r"too many requests|rate limit|лимит.*сообщен|usage limit",
    composer_exclude_classes=("cm-content", "cm-editor", "CodeMirror"),
)
