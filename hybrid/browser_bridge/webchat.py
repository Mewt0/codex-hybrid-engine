"""Full automation of an external web chat over CDP, as an explicit state machine.

Flow:

    diagnose page -> composer ready -> insert prompt (verified) -> submit
    -> a *new* assistant message appears -> stream stops -> extract -> import

Two properties matter more than anything else here:

* the automation never reads "the last assistant message" on faith. It records
  a baseline (message count, last message key/hash, URL) before submitting and
  reads the answer only from the message that appeared afterwards, so a stale
  or previous answer can never be imported;
* every wait is a condition with a deadline and adaptive polling (150 ms while
  the page is reacting, 500 ms while the model thinks, 1.5 s during a long
  stream). Nothing sleeps for a fixed number of seconds to "be safe".

Failures raise :class:`WebChatError` carrying the stage that failed, and write
state.json / screenshot.png / dom-snippet.html / timing.json when an artifacts
directory is configured.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .browser_state import (
    PageState,
    PageStateReader,
    RunTrace,
    answer_js,
    redact_url,
    registry_js,
)
from .cdp import ChromePage, CdpError

# Backwards-compatible alias: external callers used to import this constant.
LAST_ANSWER_JS = answer_js(None)

# Stages of one automation run, in order. The last one is reached only on error.
IDLE = "IDLE"
COMPOSER_READY = "COMPOSER_READY"
PROMPT_INSERTED = "PROMPT_INSERTED"
SUBMITTED = "SUBMITTED"
ASSISTANT_STARTED = "ASSISTANT_STARTED"
STREAMING = "STREAMING"
STREAM_FINISHED = "STREAM_FINISHED"
ANSWER_EXTRACTED = "ANSWER_EXTRACTED"
FAILED = "FAILED"

# Above this size a single Input.insertText call is slow and lossy on a React
# editor, so the prompt goes in as verified chunks.
CHUNK_THRESHOLD = 20000
CHUNK_SIZE = 4000
# A short pause between chunks: the editor needs a task turn to process each
# one. This is pacing for the input subsystem, not "sleeping to be safe".
CHUNK_PACING_SECONDS = 0.05
# Losing more than this share of the prompt means it did not land intact.
# Growing larger is expected: innerText normalises whitespace.
MAX_PROMPT_LOSS = 0.02
# How many characters of head/tail are compared to prove the right text landed.
PROMPT_PEEK_CHARS = 24
# An answer shorter than this is treated as "the page produced nothing".
MIN_ANSWER_CHARS = 1
# Quiescence required to call the stream finished when we never saw the Stop
# button. Without that explicit signal, a short pause must not end the wait.
NO_SIGNAL_QUIET_SECONDS = 10.0

# Every element the automation touches is resolved through the selector
# registry, never by a hard-coded query. On the current ChatGPT build a bare
# `div[contenteditable="true"]` matches the CodeMirror editor of a Canvas
# answer, so a hard-coded query would type the prompt into the user's code.
_COMPOSER_PICK = (
    "  const REG = " + registry_js() + ";\n"
    "  const pick = (name) => {\n"
    "    for (const entry of (REG[name] || [])) {\n"
    "      let node = null;\n"
    "      try { node = document.querySelector(entry[0]); } catch (error) { node = null; }\n"
    "      if (node) { return node; }\n"
    "    }\n"
    "    return null;\n"
    "  };\n"
    "  const box = pick('composer');\n"
)

FOCUS_JS = """
/*hybrid:focus*/
(() => {
__PICK__  if (!box) { return false; }
  box.focus();
  return true;
})()
""".replace("__PICK__", _COMPOSER_PICK)

CLEAR_JS = """
/*hybrid:clear*/
(() => {
__PICK__  if (!box) { return false; }
  box.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(box);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand('delete');
  return true;
})()
""".replace("__PICK__", _COMPOSER_PICK)

SUBMIT_JS = """
/*hybrid:submit*/
(() => {
__PICK__  if (!box) { return false; }
  const scope = box.closest('form') || box.parentElement;
  for (const entry of (REG.send_button || [])) {
    const query = entry[0];
    let node = null;
    try { node = (scope && scope.querySelector(query)) || document.querySelector(query); } catch (error) { node = null; }
    if (node && !node.disabled) { node.click(); return true; }
  }
  return false;
})()
""".replace("__PICK__", _COMPOSER_PICK)


class WebChatError(CdpError):
    """An expected automation failure, tied to the stage that produced it."""


def _squash(value: str) -> str:
    """Collapse whitespace the way the browser's innerText does."""
    return " ".join((value or "").split())


@dataclass
class AnswerBaseline:
    """What the page looked like *before* submitting, so "new" is provable."""

    url: str = ""
    assistant_count: int = 0
    last_key: str = ""
    last_hash: str = ""

    @classmethod
    def of(cls, state: PageState) -> "AnswerBaseline":
        return cls(state.url, state.assistant_count, state.last_answer_key, state.last_answer_hash)

    def to_dict(self) -> dict:
        # Redacted: the baseline is echoed into the run trace (`timing.json`),
        # which is a diagnostic artifact and must not carry the conversation id.
        return {
            "url": redact_url(self.url),
            "assistant_count": self.assistant_count,
            "last_key": self.last_key,
            "last_hash": self.last_hash,
        }


@dataclass
class ChatAnswer:
    text: str
    seconds: float
    effort: str | None = None
    answered: bool = False
    # False when the stream was still moving at the deadline: the text is a
    # partial answer and must not be imported as a finished one.
    complete: bool = True
    conversation_url: str = ""
    key: str = ""
    stage: str = ""
    baseline: AnswerBaseline | None = None
    trace: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "answered": self.answered,
            "complete": self.complete,
            "seconds": round(self.seconds, 1),
            "chars": len(self.text),
            "effort": self.effort,
            "conversation_url": self.conversation_url,
            "key": self.key,
            "stage": self.stage,
        }


class WebChatAutomation:
    """Drives one web chat page: diagnose, type, submit, wait, read the answer."""

    def __init__(
        self,
        page: ChromePage,
        reader: PageStateReader | None = None,
        stable_seconds: float = 2.0,
        startup_seconds: int = 180,
        artifacts_dir: str | Path | None = None,
        poll_seconds: float | None = None,
        no_signal_quiet_seconds: float = NO_SIGNAL_QUIET_SECONDS,
        profile=None,
    ):
        self.page = page
        if profile is None and reader is not None:
            profile = reader.profile
        if profile is None:
            from .sites import default_site

            profile = default_site()
        self.profile = profile
        self.reader = reader or PageStateReader(page, profile=profile)
        self.stable_seconds = stable_seconds
        self.startup_seconds = startup_seconds
        self.no_signal_quiet_seconds = no_signal_quiet_seconds
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        # Legacy knob: fixed polling was replaced by the adaptive schedule in
        # PageStateReader.wait_until. Kept only so old call sites still import.
        self.poll_seconds = poll_seconds
        self.trace = RunTrace()
        self.stage = IDLE
        self.last_diagnostics: Path | None = None
        # True once the Stop button was actually observed during this run. It is
        # the only trustworthy "the model is generating" signal, and its
        # disappearance is what lets us call an answer finished rather than
        # merely paused.
        self.saw_stop_button = False
        # True once the site stated the turn's generation state at all, which is
        # a stronger signal than the Stop button when it is available.
        self.saw_turn_state = False

    # -- public API ---------------------------------------------------------

    def state(self) -> dict:
        """Legacy flat dict, kept for `hybrid browser read` and old callers."""
        state = self.reader.read(fast=True)
        return {
            "chars": state.composer_chars,
            "sendReady": state.send_enabled,
            "sending": state.stop_button,
            "answers": state.assistant_count,
            "answerChars": state.last_answer_chars,
            "answerTail": state.last_answer_tail,
        }

    def page_state(self) -> PageState:
        return self.reader.read()

    def effort_label(self) -> str | None:
        """Best-effort read of the model/effort label shown in the header.

        A transport failure here is reported as "unknown" rather than raised: it
        is a cosmetic read taken after the real work already succeeded, and it
        must not turn a good answer into a failed run.
        """
        if not self.profile.supports_effort or self.profile.detect_effort is None:
            return None
        try:
            return self.profile.detect_effort(self.page)
        except CdpError as exc:
            self.trace.note(f"could not read the effort label: {exc}")
            return None

    def diagnose(self) -> dict:
        """Interactive diagnosis: the raw URL and title are for the human now."""
        state = self.reader.read()
        return {
            **state.to_dict(redact=True),
            # Printed to the terminal, never written to an artifact file.
            "url": state.url,
            "title": state.title,
            "selector_report": state.report(),
            "blockers": state.blockers(),
        }

    def ensure_ready(self, timeout: float = 20.0) -> PageState:
        """Fail fast on a login wall / captcha / rate limit, then await a composer.

        The expensive probe (the one that reads page text) runs at most once a
        second here; between those checks the cheap probe polls every 150 ms.
        Polling the full probe for 20 s straight would rebuild the page text
        hundreds of times on a long conversation.
        """
        required = ("composer", "send_button", "assistant_message", "answer_body")
        if any(not self.profile.selectors.get(name) for name in required):
            missing = ", ".join(name for name in required if not self.profile.selectors.get(name))
            state = self.reader.read()
            raise WebChatError(
                f"site profile {self.profile.name!r} has no verified selectors for: {missing}; "
                f"refusing browser interaction. selector_report={state.report()!r}; [{state.render()}]"
            )
        deadline = time.time() + timeout
        while True:
            state = self.reader.read()
            self.trace.note_selectors(state)
            fatal = state.fatal_blockers()
            if fatal:
                self.stage = FAILED
                raise WebChatError("cannot drive this page: " + "; ".join(fatal) + f" [{state.render()}]")
            if state.composer:
                self.stage = COMPOSER_READY
                return state
            if time.time() >= deadline:
                self.stage = FAILED
                raise WebChatError(f"no message composer found. [{state.render()}]")
            try:
                self.reader.wait_until(
                    lambda current: current.composer,
                    "the message composer",
                    timeout=min(1.0, max(0.05, deadline - time.time())),
                    trace=self.trace,
                    fast=True,
                )
            except CdpError:
                # No composer within a second; loop and take a full probe again
                # so a login wall that appeared meanwhile is still caught.
                continue

    def insert_prompt(self, text: str, timeout: float = 20.0) -> PageState:
        """Clear the composer and type the prompt, verifying what actually landed."""
        if not text:
            raise WebChatError("refusing to send an empty prompt")
        expected = len(text.strip())

        state = self.reader.read(fast=True)
        if state.composer_chars:
            self._clear()
            try:
                self.reader.wait_until(
                    lambda current: current.composer_chars == 0,
                    "an empty composer",
                    timeout=min(timeout, 10.0),
                    trace=self.trace,
                    fast=True,
                )
            except CdpError:
                self.trace.note_retry("insert_prompt", "composer did not clear")

        self._type(text, chunked=len(text) > CHUNK_THRESHOLD)
        state = self._await_typed(expected, timeout)
        if not self.prompt_landed(state, text):
            self.trace.note_retry(
                "insert_prompt",
                f"composer holds {state.composer_chars} of {expected} characters "
                f"(head={state.composer_head!r}); retrying in chunks",
            )
            self._clear()
            time.sleep(0.2)
            self._type(text, chunked=True)
            state = self._await_typed(expected, timeout)
        if not self.prompt_landed(state, text):
            self.stage = FAILED
            raise WebChatError(
                f"the prompt did not land in the composer intact: {state.composer_chars} of {expected} "
                f"characters, head={state.composer_head!r}, tail={state.composer_tail!r}. [{state.render()}]"
            )
        self.stage = PROMPT_INSERTED
        return state

    @staticmethod
    def prompt_landed(state: PageState, text: str) -> bool:
        """Did *this* prompt land in the composer?

        Length alone is a bad check in both directions: the composer reports
        `innerText`, which collapses runs of blank lines (a 12-character prompt
        with empty lines comes back as 21 characters, +75%), and a 5% tolerance
        on a 20 000-character prompt would silently accept losing 1000 of them.

        So the two failure modes are separated:

        * **shrinking** below the source means characters were dropped — always
          an error, regardless of how small the loss looks in percentage terms;
        * **growing** is normal whitespace normalisation, and is only rejected
          when it is absurd;
        * and the first/last characters of the source must be present, which is
          what actually proves the right prompt is in the box.
        """
        if state.composer_chars <= 0:
            return False
        source = _squash(text)
        if not source:
            return state.composer_chars > 0

        dropped = len(text.strip()) - state.composer_chars
        if dropped > max(16, int(len(text.strip()) * MAX_PROMPT_LOSS)):
            return False
        if state.composer_chars > len(text.strip()) * 3 + 100:
            return False

        head = _squash(state.composer_head)[:PROMPT_PEEK_CHARS]
        tail = _squash(state.composer_tail)[-PROMPT_PEEK_CHARS:]
        if head and not source.startswith(head):
            return False
        if tail and not source.endswith(tail):
            return False
        return True

    def submit_prompt(self, baseline: AnswerBaseline, timeout: float = 15.0) -> PageState:
        """Click send and prove the site accepted the message."""
        state = self.reader.wait_until(
            lambda current: current.can_submit() or current.stop_button,
            "an enabled send button",
            timeout=min(timeout, 15.0),
            trace=self.trace,
            fast=True,
        )
        submit_js = SUBMIT_JS.replace(registry_js(), registry_js(self.profile))
        if not self.page.eval(submit_js):
            self.stage = FAILED
            raise WebChatError(
                f"the send button was not available (send_enabled={state.send_enabled}, "
                f"composer={state.composer_chars} chars). [{state.render()}]"
            )
        self.stage = SUBMITTED

        state = self.reader.wait_until(
            lambda current: self._accepted(current, baseline),
            "the site to accept the message",
            timeout=timeout,
            trace=self.trace,
            fast=True,
        )
        return state

    def read_answer(
        self,
        timeout_seconds: int = 600,
        startup_seconds: int = 180,
        state: PageState | None = None,
    ) -> ChatAnswer:
        """Wait for whatever is already streaming to settle, then read it.

        Unlike :meth:`ask` there is no baseline to compare against: this is for
        a conversation the user (or a previous run) already submitted.
        """
        start = time.time()
        self.trace = RunTrace()
        self.stage = IDLE
        self.saw_stop_button = False
        self.saw_turn_state = False
        try:
            with self.trace.stage("diagnose"):
                current = state or self.ensure_ready()
            if not current.assistant_count:
                current = self.reader.wait_until(
                    lambda probe: probe.assistant_count > 0,
                    "an assistant message",
                    timeout=startup_seconds,
                    trace=self.trace,
                    fast=True,
                )
            current = self.reader.wait_until(
                lambda probe: probe.last_answer_chars > 0 or probe.stop_button,
                "the answer to start",
                timeout=startup_seconds,
                trace=self.trace,
                fast=True,
            )
            with self.trace.stage("streaming"):
                current, complete = self._wait_for_stream_end(timeout_seconds)
            with self.trace.stage("extract"):
                text = self._extract(current.last_answer_key, current)
        except CdpError as exc:
            self.stage = FAILED
            self.trace.finish()
            self._save_failure(exc)
            raise
        self.trace.finish(current)
        return ChatAnswer(
            text=text,
            seconds=time.time() - start,
            effort=self.effort_label(),
            answered=bool(text),
            complete=complete,
            conversation_url=current.url,
            key=current.last_answer_key,
            stage=self.stage,
            trace=self.trace.to_dict(),
        )

    def ask(
        self,
        text: str,
        timeout_seconds: int = 600,
        submit: bool = True,
        startup_seconds: int | None = None,
        ready_timeout: float = 20.0,
        insert_timeout: float = 20.0,
        submit_timeout: float = 15.0,
    ) -> ChatAnswer:
        """Insert the prompt and (optionally) submit it, then read the answer.

        The three small timeouts bound the *page reaction* stages (composer up,
        prompt landed, send accepted). ``timeout_seconds`` bounds the answer
        itself, which is the only stage that is allowed to take minutes.
        """
        start = time.time()
        self.trace = RunTrace()
        self.stage = IDLE
        self.saw_stop_button = False
        self.saw_turn_state = False
        try:
            with self.trace.stage("diagnose"):
                state = self.ensure_ready(timeout=ready_timeout)

            with self.trace.stage("insert_prompt"):
                state = self.insert_prompt(text, timeout=insert_timeout)

            if not submit:
                self.trace.finish(state)
                return ChatAnswer(
                    text=state.composer_tail,
                    seconds=time.time() - start,
                    effort=self.effort_label(),
                    answered=False,
                    conversation_url=state.url,
                    stage=self.stage,
                    trace=self.trace.to_dict(),
                )

            baseline = AnswerBaseline.of(state)
            self.trace.note(f"baseline: {baseline.to_dict()}")

            with self.trace.stage("submit"):
                state = self.submit_prompt(baseline, timeout=submit_timeout)

            with self.trace.stage("wait_for_start"):
                state, target_key = self._wait_for_new_answer(
                    baseline, startup_seconds or self.startup_seconds
                )

            with self.trace.stage("streaming"):
                state, complete = self._wait_for_stream_end(timeout_seconds)

            with self.trace.stage("extract"):
                answer = self._extract(target_key, state)

            self.trace.finish(state)
            return ChatAnswer(
                text=answer,
                seconds=time.time() - start,
                effort=self.effort_label(),
                answered=bool(answer),
                complete=complete,
                conversation_url=state.url,
                key=target_key,
                stage=self.stage,
                baseline=baseline,
                trace=self.trace.to_dict(),
            )
        except CdpError as exc:
            self.stage = FAILED
            self.trace.finish()
            self._save_failure(exc)
            raise

    def send(self, text: str, settle_seconds: float | None = None) -> str:
        """Insert + submit and return the conversation URL (no answer wait)."""
        self.trace = RunTrace()
        try:
            self.ensure_ready()
            state = self.insert_prompt(text)
            baseline = AnswerBaseline.of(state)
            state = self.submit_prompt(baseline)
        except CdpError as exc:
            self.stage = FAILED
            self._save_failure(exc)
            raise
        if settle_seconds:
            time.sleep(settle_seconds)
        return str(self.page.eval("location.href") or state.url)

    # -- internals ----------------------------------------------------------

    def _accepted(self, state: PageState, baseline: AnswerBaseline) -> bool:
        if state.stop_button:
            self.saw_stop_button = True
            return True
        if state.assistant_count > baseline.assistant_count:
            return True
        if state.last_answer_key and state.last_answer_key != baseline.last_key:
            return True
        if baseline.last_hash and state.last_answer_hash and state.last_answer_hash != baseline.last_hash:
            return True
        return False

    def _wait_for_new_answer(self, baseline: AnswerBaseline, timeout_seconds: int):
        """Wait for a message that provably did not exist before the submit."""
        started = time.time()
        try:
            state = self.reader.wait_until(
                lambda current: self._new_message(current, baseline),
                f"a new assistant message (baseline had {baseline.assistant_count})",
                timeout=timeout_seconds,
                trace=self.trace,
                fast=True,
            )
        except CdpError as exc:
            self.stage = FAILED
            raise WebChatError(
                "the web chat never started answering. "
                + str(exc)
                + "\nIf the page is clearly showing an answer, the site's DOM changed and the "
                "selector registry no longer matches it: run `hybrid browser read --json` and "
                "compare its selector_report with `hybrid/browser_bridge/browser_state.py`."
            ) from exc
        self.trace.mark("assistant_started", time.time() - started)
        self.stage = ASSISTANT_STARTED

        # The answer is the first message added after the baseline. When the
        # site reuses a node instead of appending one, fall back to the last one.
        # Either way the key must be real: extraction refuses to guess.
        target_key = state.last_answer_key
        if state.assistant_count > baseline.assistant_count and len(state.assistant_keys) > baseline.assistant_count:
            target_key = state.assistant_keys[baseline.assistant_count]
        if not target_key:
            self.stage = FAILED
            raise WebChatError(
                "a new turn appeared but no readable assistant message was identified in it. "
                f"[{state.render()}]"
            )
        return state, target_key

    def _new_message(self, state: PageState, baseline: AnswerBaseline) -> bool:
        """Is there a readable assistant message that did not exist before?

        The Stop button is deliberately *not* part of this test. On a brand-new
        conversation it appears before the answer turn is in the DOM, so
        accepting it here would lock in an empty message key and the extraction
        step would then fail on a perfectly good answer. Submission itself is
        confirmed separately, by ``_accepted``.
        """
        if state.assistant_count > baseline.assistant_count and state.assistant_keys:
            return True
        if state.last_answer_key and state.last_answer_key != baseline.last_key:
            return True
        if baseline.last_hash and state.last_answer_hash and state.last_answer_hash != baseline.last_hash:
            return True
        return False

    def _wait_for_stream_end(self, timeout_seconds: int) -> tuple[PageState, bool]:
        """Wait until the answer stops changing and generation ends.

        Returns ``(state, complete)``. ``complete=False`` means we could not
        prove that generation finished, so the text may be truncated and the
        caller must not treat it as a finished result.

        "The text stopped changing" is *not* proof on its own: reasoning models
        pause for seconds with no visible delta, and a web-search/tool step can
        hide the Stop button. Completion therefore requires explicit
        end-of-generation evidence, in this order of preference:

        1. the site states the turn's generation state and says it is done;
        2. the Stop button was observed during this run and is now gone.

        Without either, the answer is reported as ``complete=False`` — a partial
        answer must never masquerade as a finished one.
        """
        deadline = time.time() + timeout_seconds
        started = time.time()
        fingerprint: tuple[int, str] | None = None
        stable_since = time.time()
        last = PageState()
        last_report = 0.0
        while time.time() < deadline:
            state = self.reader.read(fast=True)
            last = state
            self.trace.note_selectors(state)
            if state.stop_button:
                self.saw_stop_button = True
            if state.turn_state:
                self.saw_turn_state = True
            current = (state.last_answer_chars, state.last_answer_hash)
            if current != fingerprint:
                fingerprint = current
                stable_since = time.time()
                if state.last_answer_chars:
                    self.stage = STREAMING
                now = time.time()
                if state.last_answer_chars and now - last_report >= 1.0:
                    last_report = now
                    print(
                        f"  ... answer {state.last_answer_chars} chars "
                        f"(streaming={state.stop_button}, turn={state.turn_state or '-'})"
                    )
            else:
                quiet = time.time() - stable_since
                if state.last_answer_chars > 0 and not state.stop_button:
                    finished = state.turn_finished(self.profile)
                    if finished is True and quiet >= self.stable_seconds:
                        self.stage = STREAM_FINISHED
                        return state, True
                    if finished is None and quiet >= self._quiet_needed():
                        self.stage = STREAM_FINISHED
                        if not self.saw_stop_button:
                            self.trace.note(
                                "neither the Stop button nor an explicit turn state confirmed the end of "
                                f"generation; reporting the answer as incomplete after {quiet:.1f}s of quiescence"
                            )
                        return state, self.saw_stop_button
            waited = time.time() - started
            delay = self.reader.fast if waited < 10 else (self.reader.mid if waited < 60 else self.reader.slow)
            time.sleep(delay)
        if last.last_answer_chars > 0:
            # Keep the text, but say plainly that it is unfinished: importing a
            # truncated answer as a finished one is exactly the failure mode
            # this automation exists to avoid.
            self.trace.note(f"stream did not settle within {timeout_seconds}s; text is partial")
            self.stage = STREAM_FINISHED
            return last, False
        raise WebChatError(f"timed out waiting for the web chat answer after {timeout_seconds}s [{last.render()}]")

    def _quiet_needed(self) -> float:
        """How long to wait when the site never states that generation is over."""
        return self.stable_seconds if self.saw_stop_button else self.no_signal_quiet_seconds

    def _extract(self, target_key: str, state: PageState) -> str:
        """Read the answer from the exact message we identified, or fail.

        There is deliberately no "fall back to the last message" here: if the
        key we tracked is gone, the last message is by definition *some other*
        message, and quietly returning it would break the one guarantee this
        module makes.
        """
        if not target_key:
            self.stage = FAILED
            raise WebChatError(f"no assistant message was identified to read. [{state.render()}]")
        index = state.index_of(target_key)
        if index is None:
            self.stage = FAILED
            raise WebChatError(
                f"the assistant message {target_key!r} is no longer present in the conversation "
                f"(found {state.assistant_keys[-6:]}). [{state.render()}]"
            )
        text = (self.reader.answer_text(index=index) or "").strip()
        if any(label.casefold() in text.casefold() for label in self.profile.role_labels):
            self.stage = FAILED
            raise WebChatError(
                f"the selected assistant message contains a role label; refusing an ambiguous extraction. "
                f"[{state.render()}]"
            )
        if len(text) < MIN_ANSWER_CHARS:
            self.stage = FAILED
            raise WebChatError(f"the assistant message {target_key!r} is empty. [{state.render()}]")
        self.stage = ANSWER_EXTRACTED
        return text

    # -- page manipulation --------------------------------------------------

    def _type(self, text: str, chunked: bool = False) -> None:
        self.page.eval(FOCUS_JS.replace(registry_js(), registry_js(self.profile)))
        if not chunked:
            self.page.insert_text(text)
            return
        for start in range(0, len(text), CHUNK_SIZE):
            self.page.insert_text(text[start : start + CHUNK_SIZE])
            time.sleep(CHUNK_PACING_SECONDS)

    def _await_typed(self, expected: int, timeout: float) -> PageState:
        deadline = time.time() + timeout
        state = self.reader.read(fast=True)
        while time.time() < deadline:
            state = self.reader.read(fast=True)
            if state.composer_chars > 0:
                return state
            time.sleep(0.1)
        return state

    def _clear(self) -> None:
        self.page.eval(CLEAR_JS.replace(registry_js(), registry_js(self.profile)))

    def _save_failure(self, exc: Exception) -> None:
        if not self.artifacts_dir:
            return
        try:
            self.last_diagnostics = self.reader.save_diagnostics(
                self.artifacts_dir, str(exc), self.stage, self.trace
            )
        except Exception:
            # Diagnostics must never hide the original failure.
            self.last_diagnostics = None
