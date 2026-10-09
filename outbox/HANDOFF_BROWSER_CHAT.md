# Handoff: browser ChatGPT automation reads the wrong text

Everything below is real measured output from the live site. No test runs, no
summaries from memory. A fixer can work from this alone.

Repo: `F:\codex-hybrid-engine` (Windows 11, Chrome shared session signed in to
ChatGPT Plus, DevTools on `http://127.0.0.1:9333`).

Run the automation with:

```powershell
cd F:\codex-hybrid-engine
.\.venv\Scripts\python.exe -m hybrid.cli browser read `
  --url "https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980" `
  --save .tmp-chat-answer.md
```

---

# DEFECT 1 (blocking) — the extracted "answer" is the user's prompt

## Symptom

```
URL: https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980
Title: QA plan inventory screen
Mode: unknown  Reasoning effort: Высокий
Messages: 1 answers, last 6912 chars
Streaming: False  Composer: 0 chars
Selectors:
  composer: found by div.ProseMirror[contenteditable='true']
  send_button: not found
  stop_button: not found
  assistant_message: found by [data-talvt-turn-state]
  answer_body: not found
  message_key: not found
  turn_state: found by data-talvt-turn-state
  new_chat: not found
  assistant messages: 1 found
  stop button: not found
answer saved: .tmp-chat-answer.md (6912 chars)
```

The saved file is clean UTF-8 (verified with `repr()`; mojibake in a terminal is
PowerShell console rendering, not a data problem):

```python
>>> pathlib.Path('.tmp-chat-answer.md').read_text(encoding='utf-8')[:60]
'Вы сказали:# TASK FOR A CODING MODEL\nTask id: TASK-AB22322F\n'
```

So extraction started at the **user-turn label** `Вы сказали:` ("You said:"),
included the whole prompt, and **stopped at the role label**
`ChatGPT сказал:` ("ChatGPT said:") — i.e. exactly where the real answer begins:

```
Вы сказали:# TASK FOR A CODING MODEL
Task id: TASK-AB22322F
Work profile: database
Target project stack: legacy PHP backend, plain JavaScript with fetch/AJAX, MySQL, HTML and CSS. No framework, no build step, no TypeScript.

## Request
Write a functional QA plan for a legacy PHP browser game inventory screen. ...
...
## ANSWER FORMAT
## SUMMARY
<what you changed and why, 2-5 sentences>
...
## LIMITATIONS
- <anything you could not verify ...>ChatGPT сказал:
```

The real assistant answer is **16 838 characters** and starts with
`SUMMARYCreated a functional QA test plan for the legacy PHP ...`.

## What the DOM actually is

Probe output for the node matched by `[data-talvt-turn-state]` — the selector
currently registered as `assistant_message`:

```json
{
  "turn": {
    "tag": "div",
    "turnState": "complete",
    "cls": "group flex flex-col",
    "textLen": 23750,
    "textHead": "Вы сказали:# TASK FOR A CODING MODEL Task id: TASK-AB22322F "
  },
  "turnTail": "esponse shapes, and supported actions must remain unchanged unless a separate, explicitly approved change is introduced.",
  "counts": { "insideDil": 1, "insideRoles": 1, "insideBubbles": 1, "insideTurnKeys": 0,
              "documentBubbles": 1, "documentDil": 1 },
  "bubbles": [
    { "tag": "div", "userBubble": true, "cls": "bg-user-message text-user-message",
      "textLen": 6886, "textHead": "# TASK FOR A CODING MODEL Task id: TASK-AB22322F Work profil" }
  ],
  "roleNodes": [
    { "tag": "h4", "role": "assistant", "cls": "sr-only m-0 select-none",
      "textLen": 15, "textHead": "ChatGPT сказал:" }
  ],
  "dilNodes": [
    { "tag": "div", "dilId": "ace664a4-deb",
      "cls": "DilRenderer-tB76Jj DilResponseRoot-HfQrEh Reveal-k2IWvM",
      "textLen": 16838, "textHead": "SUMMARYCreated a functional QA test plan for the legacy PHP " }
  ]
}
```

The node is the **whole exchange**, not the assistant message:

```
div.group.flex.flex-col [data-talvt-turn-state="complete"]        textLen 23750
├── div[data-user-message-bubble]  .bg-user-message                textLen  6886   ← PROMPT
├── h4[data-conversation-role="assistant"]  "ChatGPT сказал:"      textLen    15   ← role label
└── div[data-dil-message-id]  .DilRenderer/.DilResponseRoot        textLen 16838   ← ANSWER
```

Note `6886 + 15 + 16838 = 23739`, and the saved text was `6912` — the user bubble
plus label plus separators. The extraction is not reading the answer at all.

## Root cause A — `[data-talvt-turn-state]` is registered as the assistant message

`hybrid/browser_bridge/browser_state.py:86-99`:

```python
    "assistant_message": (
        Selector('[data-message-author-role="assistant"]', 0.95, "legacy role attribute"),
        Selector("[data-talvt-turn-state]", 0.9, "live answer turn with a generation state"),
        Selector('[data-conversation-role="assistant"]', 0.5, "role label inside the turn"),
        Selector('[data-testid^="conversation-turn"] [data-message-author-role]', 0.4, "turn wrapper"),
    ),
    "answer_body": (
        Selector(".markdown", 0.8, "rendered markdown container"),
        Selector('[class*="markdown"]', 0.4, "class name variant"),
        Selector("[data-dil-message-id]", 0.5, "rendered content block (live build)"),
    ),
```

`[data-talvt-turn-state]` is the **exchange wrapper**. Everything downstream then
treats "the wrapper's text" as the answer. The attribute is genuinely useful, but
only as a *generation state* source (it reads `in_progress` while streaming and
`complete` afterwards — that part works and is used to prove the stream ended).
It must not be the message identity.

## Root cause B — the state probe grabs the first registry entry, not the matched one

`hybrid/browser_bridge/browser_state.py:246-251`:

```js
  const bodyEntry = (REG.answer_body || [])[0];
  const bodyQuery = bodyEntry ? bodyEntry[0] : null;
  const textOf = (node) => {
    let body = node;
    try { body = (bodyQuery && node.querySelector(bodyQuery)) || node; } catch (error) { body = node; }
    return (body.textContent || '').trim();
  };
```

It uses the **first registered** `answer_body` selector (`.markdown`), which does
not exist on this build, and then silently falls back to `|| node` — the whole
exchange. Hence `last=23750` in the probe while the saved file was 6912.

## Root cause C — the extractor resolves the body differently

`hybrid/browser_bridge/browser_state.py:353-357` (`ANSWER_JS`, used by
`PageStateReader.answer_text`, `browser_state.py:748`) does iterate properly:

```js
  let body = node;
  for (const entry of (REG.answer_body || [])) {
    try { body = node.querySelector(entry[0]) || body; } catch (error) { body = node; }
    if (body !== node) { break; }
  }
  return (body.textContent || '').trim();
```

So the probe and the extractor disagree about what "the answer body" is. Two code
paths, two different answers for the same page. That is the architectural defect
behind the visible symptom.

## Suggested fix direction

1. Redefine `assistant_message` around an assistant-only anchor. Live-verified
   candidates:
   - `h4[data-conversation-role="assistant"]` (role label; its `textLen` is 15),
   - `div[data-dil-message-id]` inside `.DilResponseRoot` (the rendered answer).
   The reliable definition is probably "the closest ancestor of
   `[data-conversation-role="assistant"]` that contains a `[data-dil-message-id]`,
   excluding any `[data-user-message-bubble]` subtree".
2. Keep `[data-talvt-turn-state]` only in the `turn_state` registry entry.
3. Share one "body of this message" implementation between the state probe and
   `ANSWER_JS`. Never use `REG.x[0]`; always use the entry that matched.
4. Add a hard guard: if the extracted text starts with the user-turn label
   (`Вы сказали:` / `You said:`) or contains a `[data-user-message-bubble]`
   subtree, treat it as a failed extraction, not as an answer.
5. `webchat._extract` (`hybrid/browser_bridge/webchat.py:698-716`) already refuses
   an unknown key and an empty message; extend it to refuse a *wrong* message.

---

# DEFECT 2 (history, already fixed — do not revert)

On a **new** conversation the Stop button appears **before** the answer turn
exists in the DOM. `_new_message` used to accept `state.stop_button` as proof
that "a new answer appeared", which locked in an empty message key, and the run
then died on a perfectly good 23 750-character answer:

```
ERROR: browser automation failed at stage FAILED: no assistant message was identified to read.
[url=https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980 mode=unknown
 signed_in=True signals=not read composer=True(0 by div.ProseMirror[contenteditable='true'])
 send=False(by ?) stop=False turn=complete assistants=1 last=23750/aeeba8d3]
```

Fixed in `hybrid/browser_bridge/webchat.py:605` (`_new_message` no longer looks at
the Stop button; submission is confirmed separately by `_accepted`), plus a
non-empty target-key guard in `_wait_for_new_answer`
(`hybrid/browser_bridge/webchat.py:568`) and a regression test
`test_stop_button_before_the_turn_is_not_an_answer`.

The streaming log from that same run shows the state machine itself working:

```
new conversation: https://chatgpt.com/ (assistants=0)
submitting ...
  ... answer 6897 chars (streaming=True, turn=complete)
  ... answer 6944 chars (streaming=True, turn=in_progress)
  ... answer 22866 chars (streaming=False, turn=complete)
  ... answer 23750 chars (streaming=False, turn=complete)
```

---

# DEFECT 3 (history, already fixed — do not revert)

`browser read` / `browser at` navigated and immediately probed, describing an
un-hydrated SPA shell. The same conversation that has a 16 350-character answer
reported:

```
composer: found by textarea          ← the last-resort fallback matched the shell
assistant messages: 0 found
```

Fixed by `PageStateReader.wait_ready` (`browser_state.py:760`) which waits for
**selector confidence** `>= 0.8`, not merely "some element matched", and by
calling it from `browser read` in `hybrid/cli.py`.

---

# Known hazard: Canvas answers are contenteditable code editors

On a conversation whose answer renders as a Canvas, `div[contenteditable="true"]`
matches a **CodeMirror editor**, not the composer:

```json
{ "firstContentEditable": { "cls": "cm-content", "h": 4664,
    "placeholder": "Редактировать код", "text": "from __future__ import annotations..." },
  ".ProseMirror":         { "w": 288, "h": 36,
    "placeholder": "Спросить ChatGPT", "text": "" },
  "allCount": 5 }
```

Typing or clearing there would destroy the user's code. Mitigated: the composer
registry excludes `.cm-content` (`browser_state.py:86`), the probe reports
`composerIsCodeEditor`, and `ensure_ready` refuses to type when it is true. Keep
that guard.

---

# Live selector facts (all measured, same build)

| What | State |
|---|---|
| `#prompt-textarea` | **gone** (0) |
| composer | `div.ProseMirror[contenteditable='true']`, placeholder `Спросить ChatGPT` |
| `button[data-testid="send-button"]` | **gone** (0) |
| send button | exists only with a non-empty composer: `button[aria-label="Отправить"][type=submit]`; matched by `aria-label*="Отправ"` |
| `button[data-testid="stop-button"]` | **gone** (0); `aria-label*="Останов"/"Stop"` also 0 |
| `[data-message-author-role]` | **gone** (0) |
| `.markdown` | **gone** (0) |
| `article` | **gone** (0) |
| `[data-testid^="conversation-turn"]` | **gone** (0) |
| assistant turn | `[data-talvt-turn-state]` = **exchange wrapper** (see Defect 1) |
| generation state | `data-talvt-turn-state` = `in_progress` / `complete` |
| role label | `h4[data-conversation-role="assistant"]` |
| user message | `[data-user-message-bubble]` |
| answer body | `div[data-dil-message-id]`, classes `DilRenderer-tB76Jj DilResponseRoot-HfQrEh Reveal-k2IWvM` |
| action bar (assistant) | `div.turn-action-controls` (unhashed class, useful anchor) |
| message key | `data-turn-key` (UUID, seen on an earlier conversation), `data-content-search-turn-key` (`fallback-turn-0`) |
| `document.title` | the conversation name, derived from the first user message |
| other live attributes | `data-above-composer-conversation-id`, `data-above-composer-portal`, `data-chatgpt-search-message-ids`, `data-chatgpt-selection-message-id`, `data-dil-source-message-id`, `data-chatgpt-agent-turn-start`, `data-thread-user-message-navigation-content` |

The page is a plain DOM: **no shadow roots** (`shadowCount: 0`) and no content
iframe (only a 0-width `cdn.platform.openai.com/.../runner.html`). Text is
reachable with `querySelectorAll` from the top-level document.

---

# Reproduction commands (no tests)

```powershell
cd F:\codex-hybrid-engine

# A. The defect, end to end
.\.venv\Scripts\python.exe -m hybrid.cli browser read `
  --url "https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980" `
  --save .tmp-chat-answer.md
Get-Content .tmp-chat-answer.md -TotalCount 12

# B. Full live DOM signals (counters, data-* attributes, visible labels)
.\.venv\Scripts\python.exe tools\inspect_live_dom.py `
  "https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980"

# C. A whole automation run, no sending risk on an existing chat
.\.venv\Scripts\python.exe -m hybrid.cli browser chat `
  --file .\some-prompt.md --send --new-conversation --timeout 420
```

`browser read --json` prints the raw state including `selector_report`.

---

# Constraints for the fixer

- Keep the stdlib-only CDP path (`hybrid/browser_bridge/cdp.py`); no Playwright
  dependency is available (`importlib.util.find_spec('playwright')` → `None`).
- `hybrid/browser_bridge/webchat.py` is a state machine, not a polling loop:
  adaptive polling 150 ms / 500 ms / 1.5 s, every wait is a predicate with a
  deadline.
- Answer completion must stay **proven**, not guessed: the site's own turn state
  (or the Stop button observed and gone) — never "the text stopped changing".
- Do not reintroduce a silent "fall back to the last message" in `_extract`.
- Failure artifacts go to `.hybrid/tasks/<TASK>/browser/`; `dom-snippet.html` must
  stay redacted (no text nodes, no scripts, no `aria-label`, no `value`/`href`).
- `tests/test_webchat_automation.py` drives the whole machine on a fake page
  (`FakePage` answers the `/*hybrid:...*/` markers). Any new probe marker must be
  handled there or the fake silently returns `None`.
