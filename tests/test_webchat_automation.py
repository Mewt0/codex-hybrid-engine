"""Behaviour tests for the web-chat automation, driven by a fake page.

These tests never touch a browser: :class:`FakePage` answers the same JS
markers the real probes carry, so the state machine, the baseline logic, the
fail-fast rules and the failure artifacts are all exercised offline.

Covered (the failures that used to be silent):
  * no composer            -> clear error, not a mystery
  * login wall             -> fail fast, do not type into a login page
  * disabled send button   -> error plus a saved diagnostic bundle
  * successful answer      -> extracted, and the trace has the stage timings
  * stale answer           -> never returned as the new one
  * timeout before start   -> distinct "never started answering" error
  * large prompt           -> verified chunked insert
  * import without force   -> refused (the CLI default must stay safe)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import types
from pathlib import Path

import pytest

from hybrid.browser_bridge import chatgpt_ui
from hybrid.browser_bridge.browser_state import ANSWER_JS, STATE_JS, PageStateReader, RunTrace
from hybrid.browser_bridge.cdp import CdpError
from hybrid.browser_bridge.webchat import (
    CHUNK_THRESHOLD,
    AnswerBaseline,
    WebChatAutomation,
    WebChatError,
)

# Reused fixtures: a real git project and the bridge, for the CLI contract.
from test_browser_bridge import ANSWER, bridge  # noqa: F401
from test_engine import project  # noqa: F401

ANSWER_INDEX_RE = re.compile(r"const index = (\d+|null);")


class FakeBrowser:
    """A scriptable ChatGPT-ish page."""

    def __init__(self, composer: bool = True, login_wall: bool = False, send_enabled: bool = True):
        self.url = "https://chatgpt.com/"
        self.title = "ChatGPT"
        self.ready_state = "complete"
        self.has_composer = composer
        self.login_wall = login_wall
        self.captcha = False
        self.rate_limit = False
        self.send_enabled = send_enabled
        self.mode = "chat"
        # Composer contents are tracked as a string, like a real contenteditable.
        self.composer_text = ""
        # Assistant messages, oldest first.
        self.assistants: list[dict] = []
        self.stop_button = False
        # Scripted streaming chunks; consumed one per state probe.
        self.generation: list[str] | None = None
        # When True the submit click "succeeds" but nothing is added.
        self.swallow_submit = False
        # When True a navigation keeps the composer contents (a restored draft).
        self.keep_draft = False
        # When True the site never renders a Stop button (a broken selector, or
        # a layout that does not have one): the end of generation is unprovable.
        self.hide_stop_button = False
        self.finish_countdown: int | None = None
        self.clear_stop_after: int | None = None
        # Probes during which generation is reported before the answer turn
        # exists in the DOM (a brand-new conversation behaves this way).
        self.delay_assistant_node = 0
        self.pending_node_after: int | None = None
        # Probes during which generation continues but no text arrives.
        self.stall_probes = 0
        self.composer_is_code_editor = False
        # Explicit generation state, as the live build provides on an answer turn.
        self.turn_state: str | None = None
        self.answer_selector_variant = False
        self.user_prompt = ""
        self.insert_calls: list[str] = []
        self.probes = 0
        self.selector_hits = {
            "composer": "#prompt-textarea" if composer else None,
            "send_button": 'button[data-testid="send-button"]' if composer else None,
            "stop_button": None,
            "assistant_message": '[data-message-author-role="assistant"]',
            "new_chat": None,
        }

    # -- helpers ------------------------------------------------------------

    def add_answer(self, text: str, key: str | None = None) -> dict:
        message = {"key": key or f"msg-{len(self.assistants) + 1}", "text": text}
        self.assistants.append(message)
        return message

    def submit(self) -> bool:
        if not self.composer_text or not self.send_enabled:
            return False
        self.composer_text = ""
        self.stop_button = True
        if self.swallow_submit:
            # The click "works" and the site even shows the Stop button, but no
            # assistant message is ever created.
            self.clear_stop_after = 1
            return True
        if self.delay_assistant_node:
            # A brand-new conversation: the site reports generation (Stop button)
            # before the answer turn exists in the DOM.
            self.pending_node_after = self.delay_assistant_node
            return True
        self._start_answer()
        return True

    answer_steps: list[str] = []
    instant_answer = "## SUMMARY\nDone."

    def _start_answer(self) -> None:
        self.add_answer("")
        if self.answer_steps:
            self.generation = list(self.answer_steps)
            self.finish_countdown = None
        else:
            # A fast answer that completes between two polls: the stop button is
            # still reported for a probe or two, exactly as the real site does.
            self.generation = None
            self.finish_countdown = 2

    def _advance_generation(self) -> None:
        if self.pending_node_after is not None:
            if self.pending_node_after > 0:
                self.pending_node_after -= 1
                return
            self.pending_node_after = None
            self._start_answer()
            return
        if self.clear_stop_after is not None:
            if self.clear_stop_after > 0:
                self.clear_stop_after -= 1
                return
            self.clear_stop_after = None
            self.stop_button = False
            return
        if self.finish_countdown is not None:
            if self.finish_countdown > 0:
                self.finish_countdown -= 1
                return
            self.finish_countdown = None
            self.assistants[-1]["text"] = self.instant_answer
            self.stop_button = False
            return
        if self.stall_probes > 0:
            # A thinking pause: generation continues, but no text arrives yet.
            self.stall_probes -= 1
            return
        if self.generation and self.stop_button:
            self.assistants[-1]["text"] += self.generation.pop(0)
            if not self.generation:
                self.stop_button = False

    def state_raw(self, signals_checked: bool = True) -> dict:
        self.probes += 1
        self._advance_generation()
        keys = [message["key"] for message in self.assistants]
        last = self.assistants[-1] if self.assistants else None
        last_text = last["text"] if last else ""
        return {
            "url": self.url,
            "title": self.title,
            "readyState": self.ready_state,
            "signalsChecked": signals_checked,
            "signedIn": bool(self.has_composer and not self.login_wall),
            "loginWall": self.login_wall if signals_checked else False,
            "captcha": self.captcha if signals_checked else False,
            "rateLimit": self.rate_limit if signals_checked else False,
            "composer": self.has_composer,
            "composerChars": len(self.composer_text.strip()),
            "composerHead": self.composer_text.strip()[:60],
            "composerTail": self.composer_text.strip()[-40:],
            "composerIsCodeEditor": self.composer_is_code_editor,
            "sendButton": bool(self.has_composer),
            "sendEnabled": bool(self.send_enabled and self.composer_text),
            "stopButton": bool(self.stop_button and not self.hide_stop_button),
            "turnState": self.turn_state,
            "mode": self.mode,
            "chatModeAvailable": True,
            "newChatButton": False,
            "assistantCount": len(self.assistants),
            "assistantKeys": keys,
            "lastAnswerKey": keys[-1] if keys else "",
            "lastAnswerChars": len(last_text),
            "lastAnswerHash": f"{abs(hash(last_text)) % (16**8):08x}" if last_text else "",
            "lastAnswerHead": last_text[:80],
            "lastAnswerTail": last_text[-60:],
            "selectorHits": self.selector_hits,
        }


class FakePage:
    """Answers the hybrid JS markers against a FakeBrowser."""

    def __init__(self, browser: FakeBrowser):
        self.browser = browser
        self.screenshots: list[Path] = []
        self.navigations: list[str] = []
        # Counts so a test can prove the hot path uses the cheap probe.
        self.fast_probes = 0
        self.full_probes = 0

    # -- ChromePage surface -------------------------------------------------

    def eval(self, expression: str, timeout: float = 30.0):
        if "/*hybrid:state:fast*/" in expression:
            self.fast_probes += 1
            return self.browser.state_raw(signals_checked=False)
        if "/*hybrid:state:full*/" in expression:
            self.full_probes += 1
            raw = self.browser.state_raw(signals_checked=True)
            if self.browser.answer_selector_variant:
                answer = self.browser.assistants[-1]["text"] if self.browser.assistants else ""
                raw.update(
                    assistantCount=1 if self.browser.assistants else 0,
                    assistantKeys=[self.browser.assistants[-1]["key"]] if self.browser.assistants else [],
                    lastAnswerKey=self.browser.assistants[-1]["key"] if self.browser.assistants else "",
                turnState="complete",
                    lastAnswerChars=len(answer),
                    lastAnswerHead=answer[:80],
                    selectorHits={
                        **raw["selectorHits"],
                        "assistant_message": "[data-dil-message-id]",
                        "answer_body": "[data-dil-message-id]",
                        "turn_state": "data-talvt-turn-state",
                    },
                )
            return raw
        if "/*hybrid:answer*/" in expression:
            if self.browser.answer_selector_variant:
                return self.browser.assistants[-1]["text"] if self.browser.assistants else ""
            match = ANSWER_INDEX_RE.search(expression)
            index = None if not match or match.group(1) == "null" else int(match.group(1))
            if not self.browser.assistants:
                return ""
            node = self.browser.assistants[-1] if index is None else self.browser.assistants[index]
            return node["text"]
        if "/*hybrid:dom*/" in expression:
            return "<html><body>fake</body></html>"
        if "/*hybrid:focus*/" in expression:
            return self.browser.has_composer
        if "/*hybrid:clear*/" in expression:
            self.browser.composer_text = ""
            return True
        if "/*hybrid:submit*/" in expression:
            return self.browser.submit()
        if "/*hybrid:ui:model-picker*/" in expression:
            return None
        if "/*hybrid:ui:menu-items*/" in expression:
            return []
        if "/*hybrid:ui:open-menu*/" in expression:
            return False
        if "/*hybrid:ui:click-tab*/" in expression:
            return True
        return None

    def insert_text(self, text: str) -> None:
        self.browser.insert_calls.append(text)
        if self.browser.has_composer:
            self.browser.composer_text += text

    def navigate(self, url: str, wait_seconds: float | None = None, timeout: float = 45.0) -> None:
        self.navigations.append(url)
        self.browser.url = url
        self.browser.assistants = []
        if not self.browser.keep_draft:
            self.browser.composer_text = ""
        self.browser.stop_button = False

    def screenshot(self, path: Path) -> bool:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.screenshots.append(path)
        return True

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return {}

    def close(self) -> None:
        return None


@pytest.fixture()
def build():
    def _build(**kwargs):
        browser = FakeBrowser(**kwargs)
        page = FakePage(browser)
        reader = PageStateReader(page, fast=0.01, mid=0.01, slow=0.01)
        return browser, page, reader

    return _build


def automation_for(browser: FakeBrowser, page: FakePage, reader: PageStateReader, **kwargs) -> WebChatAutomation:
    kwargs.setdefault("stable_seconds", 0.01)
    kwargs.setdefault("startup_seconds", 1)
    kwargs.setdefault("no_signal_quiet_seconds", 0.05)
    return WebChatAutomation(page, reader=reader, **kwargs)


# Page-reaction stages are bounded to a fraction of a second in tests; a real
# run uses the production defaults (20 s / 20 s / 15 s).
FAST = {"ready_timeout": 0.3, "insert_timeout": 0.3, "submit_timeout": 0.3}


# --- fail-fast diagnostics ---------------------------------------------------


def test_no_composer_reports_a_clear_error(build):
    browser, page, reader = build(composer=False)
    automation = automation_for(browser, page, reader)
    with pytest.raises(WebChatError, match="composer"):
        automation.ask("hello", timeout_seconds=2, submit=False, **FAST)
    assert automation.stage == "FAILED"


def test_login_wall_fails_fast_without_typing(build):
    browser, page, reader = build(composer=False, login_wall=True)
    automation = automation_for(browser, page, reader)
    with pytest.raises(WebChatError, match="not signed in"):
        automation.ask("hello", timeout_seconds=2, submit=False, **FAST)
    # Nothing was typed into a login page.
    assert browser.insert_calls == []


def test_captcha_fails_fast(build):
    browser, page, reader = build()
    browser.captcha = True
    automation = automation_for(browser, page, reader)
    with pytest.raises(WebChatError, match="human-verification"):
        automation.ask("hello", timeout_seconds=2, submit=False, **FAST)


def test_disabled_send_saves_diagnostics(build, tmp_path: Path):
    browser, page, reader = build(send_enabled=False)
    automation = automation_for(browser, page, reader, artifacts_dir=tmp_path)
    with pytest.raises(CdpError, match="send button"):
        automation.ask("hello", timeout_seconds=2, **FAST)
    assert automation.stage == "FAILED"

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["stage"] == "FAILED"
    assert (tmp_path / "screenshot.png").exists()
    assert (tmp_path / "dom-snippet.html").exists()
    assert (tmp_path / "timing.json").exists()
    assert state["selector_report"]


# --- the happy path ----------------------------------------------------------


def test_successful_answer_is_extracted_with_timings(build):
    browser, page, reader = build()
    browser.instant_answer = "## SUMMARY\nThe panel is fixed."
    automation = automation_for(browser, page, reader)
    answer = automation.ask("fix the panel", timeout_seconds=5)

    assert answer.answered is True
    assert answer.text == "## SUMMARY\nThe panel is fixed."
    assert answer.stage == "ANSWER_EXTRACTED"
    assert answer.conversation_url == "https://chatgpt.com/"
    assert answer.key == "msg-1"

    stages = [stage["stage"] for stage in answer.trace["stages"]]
    for expected in ("diagnose", "insert_prompt", "submit", "wait_for_start", "streaming", "extract"):
        assert expected in stages


def test_streaming_answer_waits_for_the_stream_to_stop(build):
    browser, page, reader = build()
    browser.answer_steps = ["Hel", "lo", " world"]
    browser.instant_answer = "Hello world"
    automation = automation_for(browser, page, reader)
    answer = automation.ask("say hello", timeout_seconds=5)
    assert answer.text == "Hello world"
    assert browser.stop_button is False


def test_dry_run_never_submits(build):
    browser, page, reader = build()
    automation = automation_for(browser, page, reader)
    answer = automation.ask("draft only", submit=False, timeout_seconds=2)
    assert answer.answered is False
    assert answer.stage == "PROMPT_INSERTED"
    assert browser.assistants == []
    assert browser.composer_text == "draft only"


# --- new-answer tracking -----------------------------------------------------


def test_stale_answer_is_never_returned(build):
    browser, page, reader = build()
    browser.add_answer("OLD ANSWER THAT MUST NOT BE IMPORTED", key="old")
    automation = automation_for(browser, page, reader)
    answer = automation.ask("new question", timeout_seconds=5)
    assert "OLD ANSWER" not in answer.text


def test_timeout_before_the_assistant_starts(build):
    browser, page, reader = build()
    browser.add_answer("OLD ANSWER", key="old")
    browser.swallow_submit = True
    automation = automation_for(browser, page, reader)
    with pytest.raises(WebChatError, match="never started answering"):
        automation.ask("new question", timeout_seconds=5, startup_seconds=1, **FAST)
    assert automation.stage == "FAILED"
    # The stale message is still there and was never returned as the answer.
    assert browser.assistants[0]["text"] == "OLD ANSWER"


def test_baseline_records_the_page_before_submit(build):
    browser, page, reader = build()
    browser.add_answer("previous turn", key="old")
    browser.instant_answer = "fresh turn"
    automation = automation_for(browser, page, reader)
    answer = automation.ask("next question", timeout_seconds=5)

    assert answer.baseline is not None
    assert answer.baseline.assistant_count == 1
    assert answer.baseline.last_key == "old"
    assert answer.key == "msg-2"
    assert answer.text == "fresh turn"


def test_answer_is_read_from_the_new_message_not_the_last(build):
    """A second answer arriving after the target must not be picked up."""
    browser, page, reader = build()
    browser.answer_steps = ["the real answer"]
    automation = automation_for(browser, page, reader)

    state = automation.ensure_ready()
    typed = automation.insert_prompt("question")
    baseline = AnswerBaseline.of(typed)
    automation.submit_prompt(baseline)
    # One stream probe materialises the scripted answer.
    assert reader.read(fast=True).last_answer_chars > 0
    assert browser.assistants[0]["text"] == "the real answer"

    # Something appended another message afterwards (a tool turn, a retry).
    browser.add_answer("unrelated later message", key="later")
    state = reader.read(fast=True)
    assert automation._extract("msg-1", state) == "the real answer"


# --- prompt insertion --------------------------------------------------------


def test_large_prompt_is_inserted_in_verified_chunks(build):
    browser, page, reader = build()
    browser.instant_answer = "ok"
    prompt = "x" * (CHUNK_THRESHOLD + 500)
    automation = automation_for(browser, page, reader)
    automation.ask(prompt, timeout_seconds=5)

    assert len(browser.insert_calls) > 1
    assert all(len(chunk) <= 4000 for chunk in browser.insert_calls)
    assert "".join(browser.insert_calls) == prompt


def test_short_prompt_is_inserted_in_one_call(build):
    browser, page, reader = build()
    automation = automation_for(browser, page, reader)
    automation.ask("short prompt", submit=False, timeout_seconds=2)
    assert browser.insert_calls == ["short prompt"]


def test_lost_prompt_is_detected(build, tmp_path: Path):
    browser, page, reader = build()
    # The editor silently drops everything that is typed.
    page.insert_text = lambda text: browser.insert_calls.append(text)
    automation = automation_for(browser, page, reader, artifacts_dir=tmp_path)
    with pytest.raises(WebChatError, match="did not land in the composer"):
        automation.ask("a prompt nobody sees", timeout_seconds=2, **FAST)
    assert (tmp_path / "state.json").exists()


# --- selector registry, diagnostics, conversation lifecycle ------------------


def test_selector_report_names_the_matching_query(build):
    browser, page, reader = build()
    state = reader.read()
    report = state.report()
    assert any(line.startswith("composer: found by #prompt-textarea") for line in report)
    assert any(line.startswith("stop_button:") for line in report)
    assert f"assistant messages: {state.assistant_count} found" in report


def test_diagnose_reports_blockers_and_url(build):
    browser, page, reader = build(composer=False, login_wall=True)
    automation = automation_for(browser, page, reader)
    payload = automation.diagnose()
    assert payload["url"] == "https://chatgpt.com/"
    assert payload["login_wall"] is True
    assert payload["blockers"]
    assert payload["selector_report"]


def test_new_conversation_requires_an_empty_composer(build):
    browser, page, reader = build()
    browser.composer_text = "leftover draft"
    # A restored draft survives the navigation to the site root.
    browser.keep_draft = True
    with pytest.raises(CdpError, match="still has"):
        chatgpt_ui.new_conversation(page, timeout=0.3)


def test_new_conversation_clears_a_previous_chat(build):
    browser, page, reader = build()
    browser.add_answer("old conversation")
    state = chatgpt_ui.new_conversation(page, timeout=1)
    assert state.assistant_count == 0
    assert state.composer is True


def test_read_answer_settles_an_in_flight_stream(build):
    """`read` mode has no baseline: it waits for the message being streamed."""
    browser, page, reader = build()
    browser.add_answer("")
    browser.stop_button = True
    browser.generation = ["Hel", "lo"]
    automation = automation_for(browser, page, reader)
    answer = automation.read_answer(timeout_seconds=5, startup_seconds=1)
    assert answer.text == "Hello"
    assert answer.stage == "ANSWER_EXTRACTED"


# --- the hot path must not read the conversation -----------------------------


def test_streaming_uses_the_cheap_probe(build):
    """Page text must not be pulled into the process on every 150 ms poll."""
    browser, page, reader = build()
    browser.answer_steps = ["a", "b", "c", "d"]
    browser.instant_answer = "abcd"
    automation = automation_for(browser, page, reader)
    automation.ask("question", timeout_seconds=5)

    assert page.fast_probes > 5, f"expected the streaming loop to poll cheaply, got {page.fast_probes}"
    assert page.full_probes <= 3, f"the expensive probe ran {page.full_probes} times"


def test_cheap_probe_never_claims_there_is_no_login_wall(build):
    browser, page, reader = build()
    browser.login_wall = True
    cheap = reader.read(fast=True)
    assert cheap.signals_checked is False
    # Unread signals must not be reported as "all clear" facts.
    assert cheap.fatal_blockers() == []
    assert cheap.blockers() == []

    full = reader.read()
    assert full.signals_checked is True
    assert full.fatal_blockers()


def test_diagnose_reports_whether_signals_were_read(build):
    browser, page, reader = build()
    automation = automation_for(browser, page, reader)
    assert automation.diagnose()["signals_checked"] is True
    assert "signals=checked" in reader.read().render()
    assert "signals=not read" in reader.read(fast=True).render()


def test_partial_answer_is_marked_incomplete(build):
    """A stream that never settles must not look like a finished answer."""
    browser, page, reader = build()
    browser.answer_steps = ["x"] * 5000
    automation = automation_for(browser, page, reader)
    answer = automation.ask("question", timeout_seconds=1, submit_timeout=5)
    assert answer.answered is True
    assert answer.complete is False
    assert answer.to_dict()["complete"] is False


# --- "stable text" is not proof that generation finished (F1) ----------------


def test_a_pause_is_not_the_end_of_the_answer(build):
    """A thinking pause longer than the stability window must not truncate.

    This is the regression the old code had: `stable_seconds` of unchanged text
    was treated as "generation finished", so a reasoning model that pauses
    mid-answer had the first half imported as the whole thing.
    """
    browser, page, reader = build()
    browser.answer_steps = ["## SUMMARY\npart one", " AND THE REST OF THE ANSWER"]
    # Three probes (~0.03 s) of silence: longer than stable_seconds (0.01 s).
    browser.stall_probes = 3
    automation = automation_for(browser, page, reader, no_signal_quiet_seconds=0.5)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.text == "## SUMMARY\npart one AND THE REST OF THE ANSWER"


def test_a_pause_is_survived_with_the_stop_button_visible(build):
    browser, page, reader = build()
    browser.answer_steps = ["first half", " second half"]
    browser.stall_probes = 3
    automation = automation_for(browser, page, reader)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.text == "first half second half"
    assert answer.complete is True


def test_unprovable_completion_is_reported_as_incomplete(build):
    browser, page, reader = build()
    browser.hide_stop_button = True
    automation = automation_for(browser, page, reader, no_signal_quiet_seconds=0.05)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.complete is False
    assert any("incomplete" in note for note in answer.trace["notes"])


def test_observed_stop_button_proves_completion(build):
    browser, page, reader = build()
    browser.instant_answer = "a finished answer"
    automation = automation_for(browser, page, reader)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.complete is True
    assert answer.text == "a finished answer"


def test_explicit_turn_state_proves_completion_without_a_stop_button(build):
    """The live build states the turn state; that beats guessing from silence."""
    browser, page, reader = build()
    browser.hide_stop_button = True  # no Stop button anywhere
    browser.turn_state = "complete"  # ...but the site says the turn is done
    automation = automation_for(browser, page, reader)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.complete is True
    assert answer.text == "## SUMMARY\nDone."


def test_turn_state_that_is_still_running_keeps_waiting(build):
    """A stated running state must not be mistaken for completion."""
    browser, page, reader = build()
    browser.hide_stop_button = True
    browser.answer_steps = ["first half"]
    browser.stall_probes = 2
    browser.turn_state = "thinking"

    import threading

    def finish() -> None:
        browser.turn_state = "complete"

    timer = threading.Timer(0.25, finish)
    timer.start()
    try:
        automation = automation_for(browser, page, reader, no_signal_quiet_seconds=5.0)
        answer = automation.ask("question", timeout_seconds=5)
    finally:
        timer.cancel()
    assert answer.complete is True


def test_unknown_turn_state_falls_back_to_the_quiet_window(build):
    browser, page, reader = build()
    browser.hide_stop_button = True
    browser.turn_state = "some-unknown-value"
    automation = automation_for(browser, page, reader, no_signal_quiet_seconds=0.05)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.complete is False  # unproven: no stop, no recognised state


def test_turn_finished_maps_known_values():
    from hybrid.browser_bridge.browser_state import PageState

    assert PageState(turn_state="complete").turn_finished() is True
    assert PageState(turn_state="COMPLETED").turn_finished() is True
    assert PageState(turn_state="thinking").turn_finished() is False
    assert PageState(turn_state="streaming").turn_generating() is True
    assert PageState(turn_state="wat").turn_finished() is None
    assert PageState(turn_state=None).turn_finished() is None


# --- prompt integrity (F2) ---------------------------------------------------


def test_blank_line_prompt_is_not_rejected(build):
    """innerText collapses blank lines: a 12-char prompt returns 21 chars."""
    browser, page, reader = build()
    automation = automation_for(browser, page, reader)
    automation.ask("a\n\n\n\n\n\n\n\n\n\nb", submit=False, timeout_seconds=2)
    assert len(browser.insert_calls) == 1  # no "retry in chunks" false failure


def test_dropped_prompt_characters_are_detected(build, tmp_path: Path):
    """A 20k prompt losing 500 characters must fail, not pass on a 5% tolerance."""
    browser, page, reader = build()
    prompt = "z" * 20000
    # The editor swallows the tail of the single-shot insert.
    original = page.insert_text

    def truncating(text: str) -> None:
        original(text[: len(text) - 500])

    page.insert_text = truncating
    automation = automation_for(browser, page, reader, artifacts_dir=tmp_path)
    with pytest.raises(WebChatError, match="did not land in the composer intact"):
        automation.ask(prompt, timeout_seconds=2, **FAST)


def test_wrong_text_in_the_composer_is_detected(build):
    browser, page, reader = build()
    prompt = "please fix the login form validation carefully" * 3
    browser.composer_text = "an entirely different prompt was already here"

    def wrong(text: str) -> None:
        browser.insert_calls.append(text)

    page.insert_text = wrong
    automation = automation_for(browser, page, reader)
    assert automation.prompt_landed(reader.read(fast=True), prompt) is False


def test_prompt_landed_accepts_normal_browser_normalisation(build):
    browser, page, reader = build()
    automation = automation_for(browser, page, reader)
    source = "line one\n\nline two\n\n\nline three"
    browser.composer_text = "line one line two line three"  # innerText collapse
    assert automation.prompt_landed(reader.read(fast=True), source) is True


# --- the answer must come from the identified message (F7) -------------------


def test_missing_answer_key_is_an_error_not_the_last_message(build):
    browser, page, reader = build()
    browser.instant_answer = "the real answer"
    automation = automation_for(browser, page, reader)
    answer = automation.ask("question", timeout_seconds=5)
    browser.add_answer("AN UNRELATED LATER MESSAGE", key="later")

    state = reader.read(fast=True)
    assert automation._extract(answer.key, state) == "the real answer"
    with pytest.raises(WebChatError, match="no longer present"):
        automation._extract("msg-gone", state)


def test_answer_extraction_refuses_an_empty_target_key(build):
    browser, page, reader = build()
    browser.add_answer("something")
    automation = automation_for(browser, page, reader)
    with pytest.raises(WebChatError, match="no assistant message was identified"):
        automation._extract("", reader.read(fast=True))


def test_live_dil_answer_is_selected_without_user_prompt_or_role_label(build):
    browser, page, reader = build()
    browser.answer_selector_variant = True
    browser.user_prompt = "# TASK FOR A CODING MODEL\nprivate prompt content"
    browser.add_answer("SUMMARYCreated a functional QA plan.", key="dil-123")

    state = reader.read()
    automation = automation_for(browser, page, reader)
    extracted = automation._extract("dil-123", state)

    assert state.last_answer_chars == len("SUMMARYCreated a functional QA plan.")
    assert extracted == "SUMMARYCreated a functional QA plan."
    assert "private prompt content" not in extracted
    assert "Вы сказали:" not in extracted
    assert "ChatGPT сказал:" not in extracted


def test_answer_probe_and_extractor_share_live_answer_resolution():
    assert "const bodyEntry = (REG.answer_body || [])[0]" not in STATE_JS
    assert "const answerText = (node) =>" in STATE_JS
    assert "data-user-message-bubble" in STATE_JS
    assert "data-user-message-bubble" in ANSWER_JS


def test_stop_button_before_the_turn_is_not_an_answer(build):
    """Live bug: on a new conversation the Stop button appears before the turn.

    Accepting it as "a new answer" locked in an empty key, and the run then died
    on a perfectly good 23k-character answer with "no assistant message was
    identified to read".
    """
    browser, page, reader = build()
    browser.delay_assistant_node = 3
    browser.answer_steps = ["the ", "whole ", "answer"]
    automation = automation_for(browser, page, reader)
    answer = automation.ask("question", timeout_seconds=5)
    assert answer.text == "the whole answer"
    assert answer.key == "msg-1"
    assert answer.answered is True


# --- tracing -----------------------------------------------------------------


def test_trace_records_selectors_and_retries(build):
    trace = RunTrace()
    browser, page, reader = build()
    state = reader.read()
    trace.note_selectors(state)
    trace.note_retry("extract", "empty message")
    with trace.stage("probe"):
        pass
    payload = trace.to_dict()
    assert payload["selector_hits"]["composer"] == "#prompt-textarea"
    assert payload["retries"][0]["stage"] == "extract"
    assert payload["stages"][0]["stage"] == "probe"
    assert "probe" in trace.render()


def test_reader_wait_until_reports_the_last_state(build):
    browser, page, reader = build()
    with pytest.raises(CdpError, match="Timed out waiting for never"):
        reader.wait_until(lambda state: False, "never", timeout=0.05)


# --- CLI contract ------------------------------------------------------------


@pytest.fixture()
def cli_args(project, monkeypatch):
    """Run `hybrid browser chat ...` with the automation itself stubbed out."""
    from hybrid import cli

    captured: dict = {}

    def fake_chat(args, settings, bridge, session):
        captured.update(vars(args))
        return 0

    monkeypatch.setattr(cli, "chat_automation_command", fake_chat)

    def run_chat(*extra: str) -> dict:
        argv = ["--project", str(project), "browser", "chat", "--task", "BTASK-TEST", *extra]
        assert cli.main(argv) == 0
        return dict(captured)

    return run_chat


def test_chat_never_forces_an_import_by_default(cli_args):
    args = cli_args("--send")
    assert args["force_import"] is False
    assert args["new_conversation"] is False
    assert args["continue_url"] is None


def test_chat_force_import_requires_the_explicit_flag(cli_args):
    assert cli_args("--send", "--force-import")["force_import"] is True


def test_chat_conversation_modes_are_wired(cli_args):
    args = cli_args("--send", "--continue", "https://chatgpt.com/c/abc")
    assert args["continue_url"] == "https://chatgpt.com/c/abc"
    assert cli_args("--send", "--new-conversation")["new_conversation"] is True
    assert cli_args("--send", "--keep-conversation")["keep_conversation"] is True


def test_archive_conversation_requires_a_chatgpt_conversation_url():
    from hybrid.browser_bridge.chatgpt_ui import archive_conversation

    with pytest.raises(CdpError, match="outside chatgpt.com"):
        archive_conversation(object(), "https://evil.example/c/123")
    with pytest.raises(CdpError, match="not one ChatGPT conversation"):
        archive_conversation(object(), "https://chatgpt.com/")


def test_archive_conversation_targets_exact_sidebar_link_and_verifies_removal():
    from hybrid.browser_bridge.chatgpt_ui import archive_conversation

    class ArchivePage:
        def __init__(self):
            self.events = []

        def eval(self, expression):
            if "const path =" in expression:
                return {"x": 12, "y": 34, "buttonId": "actions", "menuId": "menu"}
            if "aria-expanded') === 'true'" in expression:
                return True
            if "querySelectorAll('[role=menuitem]')" in expression:
                return {"x": 56, "y": 78}
            if "!Array.from(document.querySelectorAll('a[href]'))" in expression:
                return True
            pytest.fail(f"unexpected archive probe: {expression}")

        def call(self, method, params):
            self.events.append((method, params))
            return {}

    page = ArchivePage()
    assert archive_conversation(page, "https://chatgpt.com/c/created-by-this-run") is True
    assert len(page.events) == 6
    assert all(method == "Input.dispatchMouseEvent" for method, _ in page.events)
    assert page.events[0][1]["x"] == 12
    assert page.events[3][1]["x"] == 56


# --- CLI glue: artifacts, provenance, safe re-import -------------------------


def chat_args(**overrides):
    base = dict(
        task=None,
        description=None,
        file=None,
        pack=None,
        pack_files=None,
        provider="chatgpt_web",
        profile=None,
        url="https://chatgpt.com/",
        continue_url=None,
        new_conversation=False,
        keep_conversation=False,
        send=True,
        timeout=30,
        shot=None,
        force_import=False,
        allow_partial=False,
        artifacts_dir=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def chat_session(browser: FakeBrowser):
    """A BrowserSession stand-in whose open_page returns the fake tab."""
    page = FakePage(browser)
    return types.SimpleNamespace(open_page=lambda url: page), page


def test_chat_command_writes_artifacts_and_records_provenance(bridge, tmp_path: Path, monkeypatch):
    from hybrid import cli
    from hybrid.browser_bridge import chatgpt_ui

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_text = "fix the label in app.js"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    browser = FakeBrowser()
    browser.instant_answer = ANSWER
    session, page = chat_session(browser)
    archived = []
    monkeypatch.setattr(chatgpt_ui, "archive_conversation", lambda page, url: archived.append(url) or True)

    code = cli.chat_automation_command(
        chat_args(file=str(prompt_file), artifacts_dir=str(artifacts)),
        bridge_obj.settings,
        bridge_obj,
        session,
    )
    assert code == 0

    expected_sha = hashlib.sha256(prompt_file.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    prompt_meta = json.loads((artifacts / "prompt.json").read_text(encoding="utf-8"))
    assert prompt_meta["prompt_sha256"] == expected_sha
    assert prompt_meta["prompt_source"] == f"file:{prompt_file}"
    assert prompt_meta["prompt_length"] == len(prompt_text)

    answer_meta = json.loads((artifacts / "answer.json").read_text(encoding="utf-8"))
    assert answer_meta["prompt_sha256"] == expected_sha
    # The extracted answer is stripped of the trailing whitespace of the node.
    assert answer_meta["answer_sha256"] == hashlib.sha256(ANSWER.strip().encode("utf-8")).hexdigest()
    assert answer_meta["answer_chars"] == len(ANSWER.strip())
    assert answer_meta["conversation_url"] == "https://chatgpt.com/"
    assert (artifacts / "timing.json").exists()

    task = bridge_obj.history()[-1]
    assert task.prompt_sha256 == expected_sha
    assert task.conversation_url == "https://chatgpt.com/"
    assert bridge_obj.review_payload(task.task_id)["status"] == "ready_for_review"
    assert archived == ["https://chatgpt.com/"]


def test_chat_command_refuses_to_replace_a_validated_result(bridge, tmp_path: Path, monkeypatch):
    from hybrid import cli
    from hybrid.browser_bridge import chatgpt_ui

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_text = "fix the label in app.js"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    prompt_sha = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()

    browser = FakeBrowser()
    browser.instant_answer = ANSWER
    archived = []
    monkeypatch.setattr(chatgpt_ui, "archive_conversation", lambda page, url: archived.append(url) or True)

    first = bridge_obj.prepare("fix the label", "chatgpt", "frontend")
    bridge_obj.import_response(first.task_id, ANSWER)

    args = chat_args(task=first.task_id, file=str(prompt_file), artifacts_dir=str(artifacts))
    session, page = chat_session(browser)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 4
    assert archived == []  # An unaccepted import must leave cleanup for later.
    # A refused import must not relabel the task with a prompt that was never
    # accepted into it.
    assert bridge_obj.task(first.task_id).prompt_sha256 == ""

    args.force_import = True
    session, page = chat_session(browser)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 0
    task = bridge_obj.task(first.task_id)
    assert task.import_count == 2
    assert task.prompt_sha256 == prompt_sha
    assert task.prompt_source == f"file:{prompt_file}"
    # The replaced answer record is archived, not silently lost.
    assert (artifacts / "history").is_dir()
    assert list((artifacts / "history").glob("answer-*.json"))
    assert archived == ["https://chatgpt.com/"]


def test_chat_command_refuses_a_partial_answer_by_default(bridge, tmp_path: Path, monkeypatch):
    from hybrid import cli
    from hybrid.browser_bridge import chatgpt_ui

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("fix the label in app.js", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    browser = FakeBrowser()
    browser.answer_steps = ["x"] * 5000
    session, page = chat_session(browser)
    archived = []
    monkeypatch.setattr(chatgpt_ui, "archive_conversation", lambda page, url: archived.append(url) or True)

    args = chat_args(file=str(prompt_file), artifacts_dir=str(artifacts), timeout=1)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 6
    assert archived == []
    task_id = bridge_obj.history()[-1].task_id
    assert bridge_obj.task(task_id).response_sha256 is None

    args.allow_partial = True
    args.task = task_id
    session, page = chat_session(browser)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 0
    meta = json.loads((artifacts / "answer.json").read_text(encoding="utf-8"))
    assert meta["answer_complete"] is False
    assert archived == ["https://chatgpt.com/"]


def test_chat_command_keeps_created_conversation_when_requested(bridge, tmp_path: Path, monkeypatch):
    from hybrid import cli
    from hybrid.browser_bridge import chatgpt_ui

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the task", encoding="utf-8")
    browser = FakeBrowser()
    browser.instant_answer = ANSWER
    session, page = chat_session(browser)
    monkeypatch.setattr(chatgpt_ui, "archive_conversation", lambda *_: pytest.fail("must keep chat"))

    args = chat_args(file=str(prompt_file), keep_conversation=True)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 0


def test_chat_command_never_archives_a_continued_conversation(bridge, tmp_path: Path, monkeypatch):
    from hybrid import cli
    from hybrid.browser_bridge import chatgpt_ui

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("do the task", encoding="utf-8")
    browser = FakeBrowser()
    browser.url = "https://chatgpt.com/c/existing-chat"
    browser.instant_answer = ANSWER
    session, page = chat_session(browser)
    monkeypatch.setattr(chatgpt_ui, "archive_conversation", lambda *_: pytest.fail("must preserve existing chat"))

    args = chat_args(file=str(prompt_file), continue_url=browser.url)
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 0


def test_chat_command_rejects_description_with_task(bridge, tmp_path: Path):
    from hybrid import cli

    bridge_obj, project, controller = bridge
    session, page = chat_session(FakeBrowser())
    args = chat_args(task="BTASK-X", description="something else")
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 1


def test_chat_command_rejects_both_conversation_modes(bridge, tmp_path: Path):
    from hybrid import cli

    bridge_obj, project, controller = bridge
    session, page = chat_session(FakeBrowser())
    args = chat_args(task="BTASK-X", new_conversation=True, continue_url="https://chatgpt.com/c/abc")
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 1


def test_chat_command_refuses_artifacts_inside_the_repo(bridge, tmp_path: Path):
    """Diagnostics must not be writable into the tracked part of the project."""
    from hybrid import cli

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("fix the label in app.js", encoding="utf-8")
    session, page = chat_session(FakeBrowser())

    inside_repo = Path(project) / "artifacts"
    args = chat_args(file=str(prompt_file), artifacts_dir=str(inside_repo))
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 1
    assert not inside_repo.exists()
    # Nothing was prepared or sent either.
    assert bridge_obj.history() == []


def test_chat_command_allows_artifacts_under_the_state_dir(bridge, tmp_path: Path):
    from hybrid import cli

    bridge_obj, project, controller = bridge
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("fix the label in app.js", encoding="utf-8")
    browser = FakeBrowser()
    browser.instant_answer = ANSWER
    session, page = chat_session(browser)

    state_dir = Path(bridge_obj.settings.data_dir) / "custom-browser-artifacts"
    args = chat_args(file=str(prompt_file), artifacts_dir=str(state_dir))
    assert cli.chat_automation_command(args, bridge_obj.settings, bridge_obj, session) == 0
    assert (state_dir / "prompt.json").exists()
    assert (state_dir / "answer.json").exists()


# --- artifact redaction ------------------------------------------------------


def test_result_files_never_carry_the_conversation_identity(build, tmp_path: Path):
    browser, page, reader = build()
    browser.url = "https://chatgpt.com/c/68f1a2b3c4d5e6f708192a3b"
    browser.title = "My secret chat title"
    browser.instant_answer = "the answer"
    automation = automation_for(browser, page, reader, artifacts_dir=tmp_path)
    automation.ask("question", timeout_seconds=5)

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) if (tmp_path / "state.json").exists() else None
    # No failure happened, so write the bundle explicitly the way a failure does.
    reader.save_diagnostics(tmp_path, "test", "FAILED", automation.trace)
    serialised = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert "My secret chat title" not in serialised
    assert "68f1a2b3c4d5e6f708192a3b" not in serialised
    assert "https://chatgpt.com/c/<id>" in serialised
    timing = (tmp_path / "timing.json").read_text(encoding="utf-8")
    assert "My secret chat title" not in timing
    assert "68f1a2b3c4d5e6f708192a3b" not in timing
    assert state is None or "title" in state["state"]


def test_dom_probe_is_a_redacting_skeleton():
    """Structural guard on the generated JS: the allow-list must stay narrow."""
    from hybrid.browser_bridge.browser_state import DOM_JS

    assert "aria-label" not in DOM_JS, "aria-label carries the account email on the real site"
    for removed in ("script", "head", "noscript", "iframe"):
        assert removed in DOM_JS
    assert "SHOW_TEXT" in DOM_JS  # text nodes are walked and blanked
    assert "KEEP" in DOM_JS


# --- the live DOM changed under us (found by a real run) ---------------------


def test_code_editor_is_never_mistaken_for_the_composer(build):
    """A Canvas answer is a contenteditable too: typing into it destroys code."""
    browser, page, reader = build()
    browser.composer_is_code_editor = True
    automation = automation_for(browser, page, reader)
    with pytest.raises(WebChatError, match="code editor"):
        automation.ask("this must never be typed", timeout_seconds=2, **FAST)
    assert browser.insert_calls == []
    assert browser.composer_text == ""


def test_composer_registry_excludes_code_editors():
    from hybrid.browser_bridge.browser_state import SELECTORS

    queries = [selector.query for selector in SELECTORS["composer"]]
    assert queries[0] == "#prompt-textarea"
    assert any(".ProseMirror" in query for query in queries), "the current composer is a ProseMirror editor"
    generic = [query for query in queries if query.startswith("div[contenteditable")]
    assert generic, "a generic contenteditable fallback is still allowed"
    assert all("cm-content" in query for query in generic), "the generic fallback must exclude code editors"


def test_typing_js_is_generated_from_the_registry():
    """FOCUS/CLEAR/SUBMIT must not hard-code a query the registry cannot update."""
    from hybrid.browser_bridge.webchat import CLEAR_JS, FOCUS_JS, SUBMIT_JS

    for name, js in (("focus", FOCUS_JS), ("clear", CLEAR_JS), ("submit", SUBMIT_JS)):
        assert "const REG = " in js, f"{name} does not use the registry"
        assert "pick('composer')" in js, f"{name} does not resolve the composer from the registry"
        assert "cm-content" in js, f"{name} lost the code-editor exclusion"
    assert "REG.send_button" in SUBMIT_JS
    assert "send-button" in SUBMIT_JS  # the registry entry is embedded, JSON-escaped


def test_a_probe_that_matches_a_code_editor_is_reported(build):
    browser, page, reader = build()
    browser.composer_is_code_editor = True
    state = reader.read()
    assert state.composer_is_code_editor is True
    assert any("code editor" in problem for problem in state.blockers())
    assert state.fatal_blockers()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://chatgpt.com/", "https://chatgpt.com/"),
        ("https://chatgpt.com/c/68f1a2b3c4d5e6f708192a3b", "https://chatgpt.com/c/<id>"),
        ("https://chat.deepseek.com/a/chat/s/abcdef012345", "https://chat.deepseek.com/a/chat/s/<id>"),
        ("data:text/html,<b>x</b>", "data:<redacted>"),
        ("", ""),
    ],
)
def test_redact_url_keeps_shape_and_drops_ids(url, expected):
    from hybrid.browser_bridge.browser_state import redact_url

    assert redact_url(url) == expected
