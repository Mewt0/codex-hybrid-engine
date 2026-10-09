from __future__ import annotations

import pytest
from types import SimpleNamespace

from hybrid.browser_bridge.sites import site_for_provider
from hybrid.browser_bridge.webchat import WebChatAutomation, WebChatError
from test_webchat_automation import FakeBrowser, FakePage
from hybrid.browser_bridge.browser_state import PageStateReader
from test_webchat_automation import chat_args


def test_deepseek_profile_is_explicitly_unverified_and_fails_closed():
    profile = site_for_provider("deepseek_web")
    assert profile.supports_turn_state is False
    assert profile.supports_effort is False
    assert profile.supports_mode_tabs is False
    assert profile.supports_archive is False
    assert profile.selectors["composer"][0].query == 'textarea[name="search"]'
    assert profile.selectors.get("send_button", ()) == ()
    assert profile.selectors.get("assistant_message", ()) == ()
    assert profile.role_labels == ()

    browser = FakeBrowser()
    page = FakePage(browser)
    reader = PageStateReader(page, profile=profile)
    automation = WebChatAutomation(page, reader=reader, profile=profile)
    with pytest.raises(WebChatError, match="no verified selectors"):
        automation.ensure_ready(timeout=0.1)


def test_deepseek_cli_dry_run_refuses_before_opening_or_typing():
    from hybrid import cli

    bridge_obj = SimpleNamespace(settings=None)

    class Session:
        def open_page(self, url):
            pytest.fail(f"unverified DeepSeek page should not be opened: {url}")

    args = chat_args(provider="deepseek_web", file="unread-prompt.md", new_conversation=True, url=None)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, Session()) == 5

