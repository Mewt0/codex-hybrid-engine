from __future__ import annotations

from hybrid.browser_bridge.browser_state import _profile_scripts
from hybrid.browser_bridge.sites import SITES, default_site, site_for_provider, site_for_url


def test_profiles_resolve_by_provider_and_hostname():
    assert site_for_provider("deepseek_web") is SITES["deepseek"]
    assert site_for_provider("chatgpt_web") is SITES["chatgpt"]
    assert site_for_url("https://chat.deepseek.com/a/chat/s/123") is SITES["deepseek"]
    assert site_for_url("https://chatgpt.com/c/abc") is SITES["chatgpt"]
    assert site_for_url("https://example.com/") is None
    assert default_site() is SITES["chatgpt"]
    deepseek = SITES["deepseek"]
    assert deepseek.conversation_url_re.fullmatch("/a/chat/s/c22f69c7-1234-5678-9abc-def012345678")
    assert not deepseek.conversation_url_re.fullmatch("/a/chat/c22f69c7-1234-5678-9abc-def012345678")


def test_profiles_have_independent_selector_registries():
    assert SITES["chatgpt"].selectors is not SITES["deepseek"].selectors
    assert SITES["chatgpt"].selectors is not __import__("hybrid.browser_bridge.browser_state", fromlist=["SELECTORS"]).SELECTORS


def test_chatgpt_profile_retains_selector_fallbacks_and_capabilities():
    profile = SITES["chatgpt"]
    assert len(profile.selectors["composer"]) >= 3
    assert len(profile.selectors["send_button"]) >= 2
    assert profile.supports_turn_state is True
    assert profile.supports_effort is True
    assert profile.supports_archive is True


def test_script_cache_does_not_mix_site_registries_or_role_labels():
    chatgpt = _profile_scripts(SITES["chatgpt"])
    deepseek = _profile_scripts(SITES["deepseek"])
    assert chatgpt[0] != deepseek[0]
    assert '"#prompt-textarea"' in chatgpt[0]
    assert '"#prompt-textarea"' not in deepseek[0]
    assert '["you said:"' in chatgpt[0]
    assert "TURN_STATE_ATTR = \"\"" in deepseek[0]
    assert "document.body ? document.body.innerText" in deepseek[0]
    assert "document.body ? document.body.textContent" not in deepseek[0]
    assert "#cf-overlay" in deepseek[0]
    assert "#cf-turnstile" not in deepseek[0]
    assert "getClientRects().length > 0" in deepseek[0]

