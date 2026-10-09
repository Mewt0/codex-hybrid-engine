"""Live smoke check for the CDP chat automation (opt-in, not part of the suite).

Launches headless Chrome, loads a `data:` page with ChatGPT-shaped markup and a
tiny script that pretends to answer, then drives the real
:class:`~hybrid.browser_bridge.webchat.WebChatAutomation` through the whole
state machine: diagnose -> clear -> insert -> submit -> new message -> stream
-> extract. This is what proves the registry-driven JS and the CDP calls work
against a real DOM; `tests/test_webchat_automation.py` proves the logic without
a browser.

    python tools/smoke_browser_state.py
"""

from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge import browser_state as bs
from hybrid.browser_bridge.browser_state import PageStateReader
from hybrid.browser_bridge.cdp import ChromePage, CdpError, find_chrome
from hybrid.browser_bridge.webchat import AnswerBaseline, WebChatAutomation
from hybrid.browser_bridge.sites import site_for_provider

MARKUP = """
<!doctype html>
<html><head><title>My secret chat title</title>
<script>window.__inline = "INLINE_SCRIPT_SECRET";</script>
</head>
<body>
  <main id="thread">
    <article data-testid="conversation-turn-1">
      <div data-message-author-role="assistant" data-message-id="msg-1">
        <div class="markdown">OLD ANSWER THAT MUST NOT BE IMPORTED</div>
      </div>
    </article>
    <button data-testid="profile-button" aria-label="user@example.com">Account</button>
    <div data-testid="secret-holder" data-csrf-token="SUPERSECRETTOKEN" aria-label="Copy">SECRET CONVERSATION TEXT</div>
    <form onsubmit="return false">
      <div id="prompt-textarea" contenteditable="true"></div>
      <button type="button" data-testid="send-button">Send</button>
    </form>
  </main>
  <script>
    const CHUNKS = ['## SUMMARY\\n', 'The panel ', 'is fixed.\\n', '## LIMITATIONS\\n- none\\n'];
    document.querySelector('button[data-testid="send-button"]').addEventListener('click', () => {
      document.querySelector('#prompt-textarea').innerHTML = '';
      const turn = document.createElement('article');
      turn.setAttribute('data-testid', 'conversation-turn-new');
      turn.innerHTML = '<div data-message-author-role="assistant" data-message-id="msg-new">' +
                       '<div class="markdown"></div></div>';
      document.querySelector('#thread').appendChild(turn);
      const body = turn.querySelector('.markdown');
      const stop = document.createElement('button');
      stop.setAttribute('data-testid', 'stop-button');
      stop.textContent = 'Stop';
      document.body.appendChild(stop);
      let index = 0;
      const timer = setInterval(() => {
        body.textContent += CHUNKS[index++];
        if (index >= CHUNKS.length) { clearInterval(timer); stop.remove(); }
      }, 80);
    });
  </script>
</body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="chatgpt", help="registered site profile (chatgpt or deepseek)")
    args = parser.parse_args()
    try:
        profile = site_for_provider(args.site)
    except ValueError as exc:
        parser.error(str(exc))
    if any(not profile.selectors.get(name) for name in ("composer", "send_button", "assistant_message", "answer_body")):
        print(f"Site profile {profile.name!r} has no verified selectors; refusing to run the synthetic automation smoke.")
        return 2
    binary = find_chrome()
    if not binary:
        print("Chrome not found; nothing to check")
        return 1

    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            failures.append(name)

    page = ChromePage.launch(ROOT / ".tmp-smoke-profile", port=9444, chrome=binary)
    try:
        page.connect_page()
        page.navigate("data:text/html;charset=utf-8," + quote(MARKUP))
        reader = PageStateReader(page, fast=0.05, mid=0.05, slow=0.05, profile=profile)

        print("phase 1: page probe")
        state = reader.read()
        print(f"  {state.render()}")
        check("composer found by id", state.selector_hits.get("composer") == "#prompt-textarea")
        check("send button found", state.send_enabled)
        check("existing answer seen", state.assistant_count == 1 and state.last_answer_key == "msg-1")
        check("answer text by index", reader.answer_text(index=0).startswith("OLD ANSWER"))
        check("no login wall", state.login_wall is False)

        print("phase 1b: the DOM artifact must be a redacted skeleton")
        snippet = reader.dom_snippet()
        print(f"  snippet {len(snippet)} chars")
        for secret, label in (
            ("OLD ANSWER", "conversation text"),
            ("SECRET CONVERSATION TEXT", "page text"),
            ("SUPERSECRETTOKEN", "csrf token attribute"),
            ("INLINE_SCRIPT_SECRET", "inline script body"),
            ("data-csrf-token", "sensitive attribute name"),
            ("user@example.com", "account email in aria-label"),
        ):
            check(f"snippet has no {label}", secret not in snippet)
        check("snippet keeps the selector skeleton", 'data-testid="secret-holder"' in snippet)
        check("snippet keeps author role", 'data-message-author-role="assistant"' in snippet)
        check("snippet has no script tag", "<script" not in snippet.lower())

        print("phase 1c: the serialised state must not carry the conversation identity")
        serialised = json.dumps(state.to_dict(), ensure_ascii=False)
        print(f"  state url field: {state.to_dict()['url']!r}")
        check("state has no page title", "My secret chat title" not in serialised)
        check("state has no raw url", state.url not in serialised)
        check("state records a title length", state.to_dict()["title_length"] == len("My secret chat title"))
        # The interactive view is allowed to show the human what they are looking at.
        check("unredacted view keeps the url", state.to_dict(redact=False)["url"] == state.url)

        print("phase 2: full ask() against the fake page")
        automation = WebChatAutomation(page, reader=reader, profile=profile, stable_seconds=0.3, artifacts_dir=ROOT / ".tmp-smoke-artifacts")
        prompt = "fix the panel " + ("x" * 200)
        answer = automation.ask(prompt, timeout_seconds=30, startup_seconds=10)
        print(f"  conversation={answer.conversation_url[:60]}...")
        print(f"  key={answer.key} stage={answer.stage} chars={len(answer.text)}")
        print(f"  text={answer.text!r}")
        check("answer extracted", "is fixed" in answer.text)
        check("answer is the new message", "OLD ANSWER" not in answer.text)
        check("answer key is the new node", answer.key == "msg-new")
        check("baseline recorded the old message", answer.baseline is not None and answer.baseline.last_key == "msg-1")
        check("composer was cleared before submit", reader.read().composer_chars == 0)
        check("final stage", answer.stage == "ANSWER_EXTRACTED")

        stages = [entry["stage"] for entry in answer.trace["stages"]]
        print(f"  stages={stages}")
        for expected in ("diagnose", "insert_prompt", "submit", "wait_for_start", "streaming", "extract"):
            check(f"trace has {expected}", expected in stages)
        print("  timings:")
        print("    " + automation.trace.render().replace("\n", "\n    "))

        print("phase 3: fail-fast on a login wall")
        page.navigate(
            "data:text/html;charset=utf-8,"
            + quote("<html><body>Log in to continue</body></html>")
        )
        try:
            WebChatAutomation(page, reader=reader).ensure_ready(timeout=0.3)
            check("login wall refused", False)
        except CdpError as exc:
            check("login wall refused", "not signed in" in str(exc))
    except CdpError as exc:
        print(f"ERROR: {exc}")
        return 2
    finally:
        page.close()

    print(json.dumps({"failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
