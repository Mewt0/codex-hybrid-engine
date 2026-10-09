# Handoff: two blockers in `F:\codex-hybrid-engine`

Reported by the agent working in this repo. Everything below is copied from real
command output, not summarised from memory. Reproduction commands are included.

Repo: `F:\codex-hybrid-engine`, branch `master`, HEAD `fe1f37e`.
Test suite at the time of writing: `204 passed` (`.venv\Scripts\python.exe -m pytest -q`).

## Environment (facts, not assumptions)

| Thing | State |
|---|---|
| OS | Windows 11 (10.0.26100), ru-RU |
| Python | 3.12.10 in `.venv` |
| Node | v24.19.0 (on PATH) |
| **PHP** | **NOT installed** (`hybrid doctor` → `PHP: NOT FOUND`) |
| **Playwright** | **NOT installed** (`importlib.util.find_spec('playwright')` → `NO`) |
| Codex CLI | `0.162.0-alpha.2`, two copies, **neither on PATH** (see Problem 1) |
| Chrome session | shared profile, DevTools on `http://127.0.0.1:9333`, signed in to ChatGPT (Plus) |
| Groq / OpenRouter | no API keys |

Because PHP and Playwright are missing, `hybrid visual run` and any functional QA
correctly report `NOT RUN`/`SKIP` rather than `PASS`. That is not part of the
problems below.

---

# PROBLEM 1 — Codex CLI runs but cannot touch the filesystem

## Symptom

`hybrid run "..." --mode safe --provider codex` finishes with:

```
TASK-9059933A
Status: failed
Mode: safe
Provider: codex
Error: Provider completed without producing file changes.
```

The model is reached, tokens are billed, and Codex answers in prose. The stored
task output is Codex explaining why it did nothing:

```
I'm blocked by the local tooling before I can create the files.

What happened:
- The shell runner fails immediately because `codex-windows-sandbox-setup.exe` is missing.
- The patch tool also failed because `demo_php_game/` does not exist yet and it cannot create the directory tree by itself here.
- The JS automation runtime hit the same sandbox helper failure.
- I did not run PHP or a server.

No project files were changed.
```

## `codex doctor` output

```
✗ sandbox      elevated Windows sandbox provisioning recorded a structured failure
─────────────────────────────────────────────────────────────
✗ sandbox      elevated Windows sandbox provisioning recorded a structured failure
    approval policy          OnRequest
    filesystem sandbox       restricted
    denied-read rules        0
    denied-read glob rules   0
    glob scan max depth      unbounded
    managed filesystem source none
    network sandbox          restricted
    linux helper             none
    execve wrapper helper    none
    sandbox backend          elevated
    denied-read restrictions false
    sandbox provisioning     failed
    error code               helper_unknown_error
  → repair or reinstall the Codex CLI from an approved distribution
```

## Minimal reproduction (no engine involved)

```powershell
$dir = Join-Path $env:TEMP 'codex-write-probe2'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
cd $dir
git init -q
git config user.email a@b.c
git config user.name probe

$codex = "C:\Users\grut\AppData\Local\OpenAI\Codex\bin\9691020b546a15b2\codex.exe"
& $codex exec -s workspace-write "Create hello.txt with the text hi"
```

Output (verbatim, warnings kept):

```
WARN codex_skills::interface: ignoring interface.icon_small: icon path with '..' must resolve under plugin assets/
WARN codex_skills::interface: ignoring interface.icon_large: icon path with '..' must resolve under plugin assets/
WARN codex_core::shell_snapshot: Failed to create shell snapshot for powershell: Shell snapshot not supported yet for PowerShell
WARN codex_otel::auth_storage: credential storage file fallback completed ... secure_outcome="not_found"

OpenAI Codex v0.162.0-alpha.2
--------
workdir: C:\Temp\codex-write-probe2
model: gpt-5.5
provider: openai
approval: never
sandbox: workspace-write [workdir, /tmp, $TMPDIR]
--------
user
Create hello.txt with the text hi
codex
I'll make the small file directly in the workspace.
apply patch
WARN codex_sandboxing::violation: recorded sandbox violation: resource=filesystem backend=windows_sandbox reason=failed_to_write_file path=unknown
ERROR codex_core::tools::router: error=Exit code: 1
Wall time: 0.2 seconds
Output:
Failed to write file C:\Temp\codex-write-probe2\hello.txt
patch: failed
C:\Temp\codex-write-probe2\hello.txt
codex
The patch writer hit a filesystem error, so I'm going to try the same tiny write through PowerShell...
exec
"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command "Set-Content -LiteralPath .\hello.txt -Value 'hi' -NoNewline; Get-Content -LiteralPath .\hello.txt" in C:\Temp\codex-write-probe2
 exited -1 in 0ms:
Failed to create unified exec process: helper_unknown_error: setup refresh had errors
ERROR codex_core::tools::router: error=exec_command failed: CreateProcess { message: "Rejected(\"Failed to create unified exec process: helper_unknown_error: setup refresh had errors\")" }
codex
I tried to create `hello.txt`, but both the patch writer and PowerShell execution failed with workspace/tool errors before the file could be written. No file was created.
tokens used
10 287
```

Result: `hello.txt NOT created`.

## Narrowing: which layer is broken

Both installed copies fail identically:

- `C:\Users\grut\.codex\.sandbox-bin\codex.exe` (333 MB)
- `C:\Users\grut\AppData\Local\OpenAI\Codex\bin\9691020b546a15b2\codex.exe`
  — this one sits **next to** `codex-windows-sandbox-setup.exe`, and still fails.

With the sandbox disabled, the same write **succeeds**. This was run once, in a
throwaway `%TEMP%` directory, purely as a diagnostic (`codex-cli-workflow`
forbids recommending bypass flags as a fix):

```powershell
& $codex exec --dangerously-bypass-approvals-and-sandbox "Create hello.txt with the text hi"
→ Created [hello.txt](C:/Temp/codex-nosandbox-probe/hello.txt) with `hi`.
→ hello.txt CREATED: hi
```

Conclusion: install, auth, model access, network and git are all fine. **Only the
elevated Windows sandbox backend fails to provision** (`helper_unknown_error`),
and that breaks both file writes and process spawning, so Codex is unusable for
any task that must change files.

## Already fixed on the engine side (do not redo)

These were real bugs in `hybrid/providers/codex.py` and are already patched:

1. **The engine launched Codex with a stripped environment.** It dropped
   `SystemRoot`, `windir`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `COMSPEC`,
   `PATHEXT`, `ProgramData`, `SystemDrive`, `OS`, `NUMBER_OF_PROCESSORS`,
   `PROCESSOR_ARCHITECTURE` and set `PATH` to only the codex directory plus
   `/usr/local/bin:/usr/bin:/bin`. On Windows a process without `SystemRoot`
   cannot initialise its network stack, and Codex looped on:

   ```
   ERROR: Reconnecting... 5/5
   ERROR: failed to refresh available models: Connection failed
   ERROR: workspace routing discovery failed
   ```

   Fixed via `CodexProvider.ENV_ALLOWED` + a Windows-aware `PATH`. Verified: with
   the engine's environment Codex now answers `PROBE_OK` (model `gpt-5.5`).

2. **The engine never passed a sandbox flag**, so `codex exec` defaulted to
   `sandbox: read-only` / `approval: never` — it could not have written files
   even with a working sandbox. The provider now passes
   `--sandbox workspace-write` (value from trusted config only; a project may not
   raise its own sandbox level — see `TRUSTED_PROVIDER_FIELDS` in
   `hybrid/config.py`).

Even with both fixes, Problem 1's underlying sandbox provisioning failure
remains, and it is outside the engine's control.

---

# PROBLEM 2 — the browser bridge extracts the prompt instead of the answer

This is the more interesting one: the automation "works" (types, submits, waits,
and correctly detects the end of generation) but **reads the wrong text**.

## Symptom

```powershell
.\.venv\Scripts\python.exe -m hybrid.cli browser read `
  --url "https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980" `
  --save .tmp-chat-answer.md
```

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
  chat: not found
  assistant messages: 1 found
  stop button: not found
answer saved: .tmp-chat-answer.md (6912 chars)
```

The saved file **starts with the user-turn label and the prompt**, not the answer.
Verified byte-level (the file is clean UTF-8; any mojibake seen in a terminal is
PowerShell console rendering, not an encoding bug):

```python
>>> pathlib.Path('.tmp-chat-answer.md').read_text(encoding='utf-8')[:60]
'Вы сказали:# TASK FOR A CODING MODEL\nTask id: TASK-AB22322F\n'
```

So the extracted text begins with `Вы сказали:` ("You said:") and the prompt
body:

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

and it **ends with the screen-reader role label** `ChatGPT сказал:` ("ChatGPT
said:") — i.e. the extraction stopped exactly where the real answer begins.

The real answer is ~16 838 characters inside the same conversation.

## What the DOM actually looks like

Probe output for the node matched by `[data-talvt-turn-state]` (the selector
currently registered as `assistant_message`):

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

So the node matched by `[data-talvt-turn-state]` is the **whole exchange**, not
the assistant message:

```
div.group.flex.flex-col [data-talvt-turn-state="complete"]      textLen 23750
├── div[data-user-message-bubble]                               textLen  6886   ← the PROMPT
├── h4[data-conversation-role="assistant"]  "ChatGPT сказал:"   textLen    15   ← role label
└── div[data-dil-message-id]  .DilRenderer/.DilResponseRoot      textLen 16838   ← the ANSWER
```

## Other live facts about this build

From `tools/inspect_live_dom.py` on the same conversation:

```json
{
  "proseMirror": 1,
  "promptTextarea": 0,
  "contentEditables": 1,
  "messageRoleAttr": 0,
  "assistantRoleAttr": 0,
  "article": 0,
  "markdown": 0,
  "turnTestid": 0,
  "sendByTestid": 0,
  "stopByTestid": 0,
  "sendByAria": 0,
  "stopByAria": 0,
  "mainTextLength": 23871
}
```

- `#prompt-textarea`, `[data-message-author-role]`, `.markdown`, `article`,
  `data-testid="send-button"`, `data-testid="stop-button"` — **all gone**.
- The composer is `div.ProseMirror[contenteditable='true']`.
- The send button only exists when the composer is non-empty; it appears as
  `button[aria-label="Отправить"][type=submit]` (the registry already matches it
  via `aria-label*="Отправ"`).
- `document.title` is the conversation name derived from the first user message.
- On a Canvas answer, `div[contenteditable="true"]` matches a **CodeMirror code
  editor** (`cm-content`), not the composer — typing into it would destroy the
  user's code. The registry now excludes `.cm-content` and refuses to type when
  the matched composer looks like a code editor.

## Second, related inconsistency

In the state probe (`hybrid/browser_bridge/browser_state.py`), the answer body is
chosen as:

```js
const bodyEntry = (REG.answer_body || [])[0];
const bodyQuery = bodyEntry ? bodyEntry[0] : null;
const textOf = (node) => {
  let body = node;
  try { body = (bodyQuery && node.querySelector(bodyQuery)) || node; } catch (error) { body = node; }
  return (body.textContent || '').trim();
};
```

It takes the **first registry entry** (`.markdown`, which is absent on this
build) rather than the entry that actually matched, then silently falls back to
the **whole node** — which is the prompt + label + answer. Meanwhile
`ANSWER_JS` (used by `answer_text()`) iterates the registry correctly and does
reach `[data-dil-message-id]`. So the probe and the extractor disagree about what
the answer body is, which is why `last=23750` (whole exchange) and the saved file
(6912) do not match each other either.

## Suggested direction (not implemented)

1. Stop treating `[data-talvt-turn-state]` as the assistant message. It is the
   exchange wrapper. Good assistant-only anchors observed live:
   - `h4[data-conversation-role="assistant"]` (role label inside the turn),
   - `div[data-dil-message-id].DilResponseRoot` (the rendered answer).
   A robust `assistant_message` is probably "the closest ancestor of
   `[data-conversation-role="assistant"]` that also contains the answer body".
2. Keep `[data-talvt-turn-state]` as a *state* source only (it gives
   `in_progress` during generation and `complete` at the end, which the bridge
   already uses to prove the stream finished).
3. Exclude `[data-user-message-bubble]` content from any answer extraction.
4. Make the probe and `ANSWER_JS` share one "body of this message" function, and
   make both use the *matched* selector, never the first registry entry.
5. Consider bounding extraction: if the extracted text contains the prompt, that
   is a hard error, not a result.

---

# What already works (so it is not re-fixed)

Verified live on the same session, not in a fake test:

- Insert into the real composer: composer `0 → 36 chars`, `prompt_landed: true`,
  then cleared back to `0`.
- `--new-conversation` opens a verified empty conversation
  (`new conversation: https://chatgpt.com/ (assistants=0)`).
- Streaming is followed and the end of generation is detected from the site's own
  turn state: the run logged
  `answer 23750 chars (streaming=False, turn=complete)` and stopped correctly.
- Fail-fast on a login wall / captcha / rate limit, before any text is typed.
- Failure artifacts are written and bounded, with a redacted `dom-snippet.html`
  (no text nodes, no scripts, no `aria-label`, no csrf/value/href attributes).
- `--force-import` is no longer the default; `--allow-partial` is required for an
  unfinished answer; provenance (`prompt_sha256`, `conversation_url`) is written
  only after an import is accepted.

Recent fixes that must not be reverted:

- The Stop button is no longer accepted as "a new answer appeared": on a new
  conversation it appears **before** the answer node exists, which previously
  locked in an empty message key and failed extraction on a good answer.
  Regression test: `test_stop_button_before_the_turn_is_not_an_answer`.
- `browser read` now waits for the SPA to mount, using selector **confidence**
  (`composer_confidence >= 0.8`), because the last-resort `textarea` fallback
  matched an un-hydrated shell and made a naive wait return instantly.
- The registry is `name -> [[query, confidence], ...]`; every generated JS probe
  is validated with `node --check`.

---

# Reproduction checklist

```powershell
cd F:\codex-hybrid-engine

# 1. Codex cannot write
$env:RUST_LOG='error'
& "C:\Users\grut\AppData\Local\OpenAI\Codex\bin\9691020b546a15b2\codex.exe" doctor

# 2. Browser bridge reads the prompt
.\.venv\Scripts\python.exe tools\inspect_live_dom.py `
  "https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980"
.\.venv\Scripts\python.exe -m hybrid.cli browser read `
  --url "https://chatgpt.com/c/6ac81fc3-c54c-83eb-9167-784a0ddd8980" `
  --save .tmp-chat-answer.md
Get-Content .tmp-chat-answer.md -TotalCount 12

# 3. Everything else is green
.\.venv\Scripts\python.exe -m pytest -q
```

Key files:

- `hybrid/browser_bridge/browser_state.py` — selector registry, probes,
  `PageStateReader`, artifact writing
- `hybrid/browser_bridge/webchat.py` — the automation state machine
- `hybrid/browser_bridge/chatgpt_ui.py` — mode/model/effort control
- `hybrid/browser_bridge/cdp.py` — stdlib CDP + WebSocket client
- `hybrid/providers/codex.py` — Codex CLI invocation
- `hybrid/cli.py` — `chat` / `read` / `context` commands
