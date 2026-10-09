"""Page diagnostics, condition waiting, selector registry and run tracing.

One JS probe returns the whole state of the page; everything else in the bridge
asks this module instead of guessing with sleeps. Two rules keep the automation
honest:

* every DOM lookup the automation depends on is declared in :data:`SELECTORS`
  with fallbacks and a confidence, so a site redesign is a one-line data change
  instead of a silent wrong-element click;
* every wait is a condition with a deadline, and a timeout reports the last
  observed page state instead of an anonymous "timed out".

A diagnostic snapshot (state JSON, screenshot, DOM snippet, timing JSON) is
written to disk whenever an automation step fails.
"""

from __future__ import annotations

import json
import re
import time
from functools import lru_cache
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .cdp import ChromePage, CdpError


def redact_url(url: str, profile=None) -> str:
    """Keep a URL recognisable without keeping the conversation id.

    ``https://chatgpt.com/c/68f...`` becomes ``https://chatgpt.com/c/<id>``: the
    host and the route shape are what diagnostics need, the identifier is not.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "<url>"
    if not parsed.hostname:
        # data:, about:, file: — no useful shape to keep.
        return f"{parsed.scheme}:<redacted>" if parsed.scheme else "<url>"
    if profile is not None:
        path = parsed.path or ""
        if profile.conversation_url_re.fullmatch(path):
            path = re.sub(r"/[0-9a-zA-Z_-]{8,}", "/<id>", path)
        else:
            path = re.sub(r"/[0-9a-zA-Z_-]{12,}", "/<id>", path)
    else:
        path = re.sub(r"/[0-9a-zA-Z_-]{12,}", "/<id>", parsed.path or "")
    netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    return f"{parsed.scheme}://{netloc}{path}"


# --- selector registry -------------------------------------------------------


@dataclass(frozen=True)
class Selector:
    """One way to find one element, and how much we trust it."""

    query: str
    confidence: float
    note: str = ""


# Ordered best-first: the probe reports which entry actually matched, so the
# diagnostics say *why* an element was found and a redesign shows up as a drop
# from the high-confidence entry to a fallback.
SELECTORS: dict[str, tuple[Selector, ...]] = {
    "composer": (
        Selector("#prompt-textarea", 0.95, "legacy stable id"),
        Selector("div.ProseMirror[contenteditable='true']", 0.9, "current ChatGPT composer"),
        Selector(".ProseMirror", 0.8, "ProseMirror editor"),
        Selector("textarea", 0.5, "classic textarea (older layouts)"),
        # Last resort only. A bare contenteditable matches the CodeMirror
        # editors of a Canvas answer, so they are excluded explicitly: typing a
        # prompt into the user's code artifact is data loss, not a mis-click.
        Selector('div[contenteditable="true"]:not(.cm-content)', 0.3, "generic editor, minus code canvases"),
    ),
    "send_button": (
        Selector('button[data-testid="send-button"]', 0.95, "primary test id"),
        Selector('button[aria-label*="Send"]', 0.6, "english aria label"),
        Selector('button[aria-label*="Отправ"]', 0.6, "russian aria label"),
        Selector('form button[type="submit"]', 0.4, "generic submit inside the form"),
    ),
    "stop_button": (
        Selector('button[data-testid="stop-button"]', 0.9, "primary test id"),
        Selector('button[aria-label*="Stop"]', 0.6, "english aria label"),
        Selector('button[aria-label*="Останов"]', 0.6, "russian aria label"),
    ),
    "assistant_message": (
        Selector('[data-message-author-role="assistant"]', 0.95, "legacy role attribute"),
        Selector('[data-dil-message-id]', 0.9, "rendered assistant response block"),
        Selector('[data-conversation-role="assistant"]', 0.5, "assistant role label (used to resolve its response)"),
    ),
    "answer_body": (
        Selector(".markdown", 0.8, "rendered markdown container"),
        Selector('[class*="markdown"]', 0.4, "class name variant"),
        Selector("[data-dil-message-id]", 0.5, "rendered content block (live build)"),
    ),
    "new_chat": (
        Selector('a[data-testid="create-new-chat-button"]', 0.7, "sidebar new chat link"),
        Selector('a[href="/"]', 0.3, "home link (ambiguous)"),
    ),
    # Not an element lookup for clicking: the attribute the current build puts
    # on an answer turn to say whether it is still generating. Verified live
    # with the value "complete".
    "turn_state": (
        Selector("[data-talvt-turn-state]", 0.9, "explicit generation state of an answer turn"),
    ),
    "message_key": (
        Selector("[data-turn-key]", 0.8, "per-turn key"),
        Selector("[data-dil-message-id]", 0.6, "rendered message id"),
        Selector("[data-message-id]", 0.5, "legacy message id"),
    ),
    "mode_tab": (
        Selector('[role="tab"]', 0.7, "chat / work mode tabs"),
        Selector('button[role="tab"]', 0.5, "button-shaped tabs"),
    ),
    "model_picker": (
        Selector('button[data-testid="model-switcher-dropdown-button"]', 0.8, "model switcher"),
        Selector('[role="button"][aria-haspopup="menu"]', 0.4, "any menu button"),
    ),
    "menu_item": (
        Selector('[role="menuitemradio"]', 0.8, "checked menu entry"),
        Selector('[role="menuitem"]', 0.7, "menu entry"),
        Selector('[role="option"]', 0.5, "listbox option"),
    ),
}

# The attribute the current ChatGPT build puts on an answer turn to describe its
# generation state. Verified live: a finished answer carries "complete".
TURN_STATE_ATTRIBUTE = "data-talvt-turn-state"
TURN_STATE_DONE = frozenset({"complete", "completed", "done", "finished"})
TURN_STATE_RUNNING = frozenset(
    {"thinking", "streaming", "generating", "in_progress", "inprogress", "pending", "searching", "running"}
)


def _registry_js(profile=None) -> str:
    """The registry as JS `name -> [[query, confidence], ...]`.

    Confidence travels with the query so the probe can say *how well* it found
    something. That is what lets readiness mean "the real composer", instead of
    "some contenteditable, possibly the shell of a page that has not mounted".
    """
    payload = {
        name: [[selector.query, selector.confidence] for selector in options]
        for name, options in (profile.selectors if profile is not None else SELECTORS).items()
    }
    return json.dumps(payload, ensure_ascii=False)


def registry_js(profile=None) -> str:
    """The selector registry as a JS object literal.

    Every probe is built from this, so a DOM lookup can never be hard-coded in
    one place and updated in another.
    """
    return _registry_js(profile)


# --- the page probe ----------------------------------------------------------

# Two probes are generated from one template.
#
#   STATE_JS      (full)  adds a whole-page text scan used to recognise a login
#                         wall, a captcha or a rate limit. Runs once per attempt
#                         (`ensure_ready`) and whenever a failure must be
#                         explained.
#   STATE_FAST_JS (cheap) reads no page text at all. It is the hot path: while
#                         streaming we probe every 150 ms, and pulling 4-6 KB of
#                         the user's conversation into the engine process on
#                         every poll is both slow and needlessly invasive.
_SIGNALS_ON = (
    "  const bodyText = (document.body ? document.body.innerText : '').slice(0, 4000);\n"
    "  const headText = bodyText.slice(0, 2000);\n"
    "  const loginWall = /log in|sign up|войти|зарегистр/i.test(headText);\n"
    "  const captcha = /verify you are human|проверка.*человек|captcha|cloudflare/i.test(bodyText);\n"
    "  const rateLimit = /too many requests|rate limit|лимит.*сообщен|usage limit/i.test(bodyText);\n"
    "  const signalsChecked = true;\n"
)

_SIGNALS_OFF = (
    "  // Page text is deliberately NOT read on the hot path.\n"
    "  const loginWall = false;\n"
    "  const captcha = false;\n"
    "  const rateLimit = false;\n"
    "  const signalsChecked = false;\n"
)

_PROBE_TEMPLATE = (
    "/*hybrid:state:__MODE__*/\n"
    "(() => {\n"
    "  const REG = " + _registry_js() + ";\n"
    "  const pick = (name) => {\n"
    "    for (const entry of (REG[name] || [])) {\n"
    "      let node = null;\n"
    "      try { node = document.querySelector(entry[0]); } catch (error) { node = null; }\n"
    "      if (node) { return { node, query: entry[0], confidence: entry[1] }; }\n"
    "    }\n"
    "    return { node: null, query: null, confidence: 0 };\n"
    "  };\n"
    "  const pickIn = (root, name) => {\n"
    "    if (!root) { return { node: null, query: null, confidence: 0 }; }\n"
    "    for (const entry of (REG[name] || [])) {\n"
    "      let node = null;\n"
    "      try { node = root.querySelector(entry[0]); } catch (error) { node = null; }\n"
    "      if (node) { return { node, query: entry[0], confidence: entry[1] }; }\n"
    "    }\n"
    "    return { node: null, query: null, confidence: 0 };\n"
    "  };\n"
    "  const matchedWithin = (root, entries) => {\n"
    "    if (!root) { return null; }\n"
    "    for (const entry of (entries || [])) {\n"
    "      try { if (root.matches(entry[0]) || root.querySelector(entry[0])) { return entry[0]; } } catch (error) { /* bad selector */ }\n"
    "    }\n"
    "    return null;\n"
    "  };\n"
    "  const confidenceFor = (name, query) => { const entry = (REG[name] || []).find((item) => item[0] === query); return entry ? entry[1] : 0; };\n"
    "  const messageNodes = () => {\n"
    "    for (const entry of (REG.assistant_message || [])) {\n"
    "      try {\n"
    "        const found = Array.from(document.querySelectorAll(entry[0]));\n"
    "        const valid = found.filter((node) => !node.closest('[data-user-message-bubble]'));\n"
    "        if (valid.length) { return valid; }\n"
    "      } catch (error) { /* try the next selector */ }\n"
    "    }\n"
    "    return [];\n"
    "  };\n"
    "  const answerBody = (node) => {\n"
    "    if (!node || node.closest('[data-user-message-bubble]')) { return null; }\n"
    "    for (const entry of (REG.answer_body || [])) {\n"
    "      try {\n"
    "        if (node.matches(entry[0])) { return node; }\n"
    "        const body = node.querySelector(entry[0]);\n"
    "        if (body && !body.closest('[data-user-message-bubble]')) { return body; }\n"
    "      } catch (error) { /* bad selector */ }\n"
    "    }\n"
    "    if (node.matches('[data-conversation-role=\\\"assistant\\\"]') || node.matches('[data-talvt-turn-state]')) {\n"
    "      const turn = node.closest('[data-talvt-turn-state]') || node.parentElement;\n"
    "      if (turn) {\n"
    "        for (const entry of (REG.answer_body || [])) {\n"
    "          try { const body = turn.querySelector(entry[0]); if (body && !body.closest('[data-user-message-bubble]')) { return body; } } catch (error) { /* bad selector */ }\n"
    "        }\n"
    "      }\n"
    "    }\n"
    "    return null;\n"
    "  };\n"
    "  const answerText = (node) => {\n"
    "    const body = answerBody(node);\n"
    "    if (!body) { return ''; }\n"
    "    const text = (body.textContent || '').trim();\n"
    "    return /^(you said:|\\u0432\\u044b \\u0441\\u043a\\u0430\\u0437\\u0430\\u043b\\u0438:)/i.test(text) ? '' : text;\n"
    "  };\n"
    "  const fnv = (text) => {\n"
    "    let hash = 0x811c9dc5;\n"
    "    for (let i = 0; i < text.length; i += 1) {\n"
    "      hash ^= text.charCodeAt(i);\n"
    "      hash = (hash + ((hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24))) >>> 0;\n"
    "    }\n"
    "    return ('0000000' + hash.toString(16)).slice(-8);\n"
    "  };\n"
    "  const composerHit = pick('composer');\n"
    "  const composer = composerHit.node;\n"
    "  const composerText = composer ? (composer.innerText || composer.value || '').trim() : '';\n"
    "  // A Canvas answer is edited in a CodeMirror instance, which is also a\n"
    "  // contenteditable. Typing a prompt into it would destroy the user's code,\n"
    "  // so the probe says out loud when the match looks like one.\n"
    "  const composerClass = composer && typeof composer.className === 'string' ? composer.className : '';\n"
    "  const composerIsCodeEditor = /cm-content|cm-editor|CodeMirror/.test(composerClass);\n"
    "  const form = composer ? (composer.closest('form') || composer.parentElement) : null;\n"
    "  const sendHit = pickIn(form, 'send_button');\n"
    "  const send = sendHit.node || pick('send_button').node;\n"
    "  const stopHit = pick('stop_button');\n"
    "__SIGNALS__"
    "  const assistants = messageNodes();\n"
    "  const assistantHit = pick('assistant_message');\n"
    "  const keyOf = (node, index) => (\n"
    "    node.getAttribute('data-message-id') || node.getAttribute('data-turn-key') ||\n"
    "    node.closest('[data-turn-key]')?.getAttribute('data-turn-key') ||\n"
    "    node.getAttribute('id') || ('index:' + index)\n"
    "  );\n"
    "  const keys = assistants.map((node, index) => keyOf(node, index));\n"
    "  const last = assistants.length ? assistants[assistants.length - 1] : null;\n"
    "  const lastText = last ? answerText(last) : '';\n"
    "  // Explicit end-of-generation state, when the build provides one. This is a\n"
    "  // real signal instead of \"the text stopped changing\", which a thinking\n"
    "  // pause can imitate.\n"
    "  const TURN_STATE_ATTR = '" + TURN_STATE_ATTRIBUTE + "';\n"
    "  const stateHolder = last\n"
    "    ? (last.hasAttribute && last.hasAttribute(TURN_STATE_ATTR)\n"
    "        ? last\n"
    "        : ((last.closest && last.closest('[' + TURN_STATE_ATTR + ']')) || (last.querySelector ? last.querySelector('[' + TURN_STATE_ATTR + ']') : null)))\n"
    "    : null;\n"
    "  const turnState = stateHolder ? (stateHolder.getAttribute(TURN_STATE_ATTR) || null) : null;\n"
    "  const modeTabEntry = (REG.mode_tab || [])[0];\n"
    "  const tabs = Array.from(document.querySelectorAll(modeTabEntry ? modeTabEntry[0] : '[role=\"tab\"]'));\n"
    "  const work = tabs.find((node) => {\n"
    "    const label = (node.innerText || '').trim();\n"
    "    return label === 'Работа' || label === 'Work';\n"
    "  });\n"
    "  const chatTab = tabs.find((node) => {\n"
    "    const label = (node.innerText || '').trim();\n"
    "    return label === 'Чат' || label === 'Chat';\n"
    "  });\n"
    "  const mode = (() => {\n"
    "    if (!work) { return 'unknown'; }\n"
    "    return work.getAttribute('aria-selected') === 'true' ? 'work' : 'chat';\n"
    "  })();\n"
    "  return {\n"
    "    url: location.href,\n"
    "    title: document.title,\n"
    "    readyState: document.readyState,\n"
    "    signalsChecked,\n"
    "    signedIn: !!composer && !loginWall,\n"
    "    loginWall,\n"
    "    captcha,\n"
    "    rateLimit,\n"
    "    composer: !!composer,\n"
    "    composerConfidence: composerHit.confidence || 0,\n"
    "    composerChars: composerText.length,\n"
    "    composerHead: composerText.slice(0, 60),\n"
    "    composerTail: composerText.slice(-40),\n"
    "    composerIsCodeEditor,\n"
    "    sendButton: !!send,\n"
    "    sendEnabled: !!(send && !send.disabled),\n"
    "    stopButton: !!stopHit.node,\n"
    "    turnState,\n"
    "    mode,\n"
    "    chatModeAvailable: !!chatTab,\n"
    "    newChatButton: !!pick('new_chat').node,\n"
    "    assistantCount: assistants.length,\n"
    "    assistantKeys: keys,\n"
    "    lastAnswerKey: keys.length ? keys[keys.length - 1] : '',\n"
    "    lastAnswerChars: lastText.length,\n"
    "    lastAnswerHash: lastText ? fnv(lastText) : '',\n"
    "    lastAnswerHead: lastText.slice(0, 80),\n"
    "    lastAnswerTail: lastText.slice(-60),\n"
    "    selectorHits: {\n"
    "      composer: composerHit.query,\n"
    "      send_button: sendHit.query || pick('send_button').query,\n"
    "      stop_button: stopHit.query,\n"
    "      assistant_message: assistantHit.query,\n"
    "      answer_body: matchedWithin(last, REG.answer_body),\n"
    "      message_key: matchedWithin(last, REG.message_key),\n"
    "      turn_state: turnState ? TURN_STATE_ATTR : null,\n"
    "      new_chat: pick('new_chat').query,\n"
    "    },\n"
    "    selectorConfidence: {\n"
    "      composer: composerHit.confidence || 0,\n"
    "      send_button: sendHit.confidence || pick('send_button').confidence || 0,\n"
    "      stop_button: stopHit.confidence || 0,\n"
    "      assistant_message: assistantHit.confidence || 0,\n"
    "      answer_body: confidenceFor('answer_body', matchedWithin(last, REG.answer_body)),\n"
    "      message_key: confidenceFor('message_key', matchedWithin(last, REG.message_key)),\n"
    "      turn_state: turnState ? confidenceFor('turn_state', TURN_STATE_ATTR) : 0,\n"
    "      new_chat: pick('new_chat').confidence || 0,\n"
    "    },\n"
    "  };\n"
    "})()"
)


def _probe_js(with_signals: bool) -> str:
    return (
        _PROBE_TEMPLATE.replace("__MODE__", "full" if with_signals else "fast")
        .replace("__SIGNALS__", _SIGNALS_ON if with_signals else _SIGNALS_OFF)
    )


STATE_JS = _probe_js(True)
STATE_FAST_JS = _probe_js(False)


# Full text of one assistant message. `__INDEX__` is replaced with a number or
# with `null` (meaning "the last one") before the expression is evaluated.
ANSWER_JS = (
    "/*hybrid:answer*/\n"
    "(() => {\n"
    "  const REG = " + _registry_js() + ";\n"
    "  let list = [];\n"
    "  const messageNodes = () => {\n"
    "    for (const entry of (REG.assistant_message || [])) {\n"
    "      try { const found = Array.from(document.querySelectorAll(entry[0])).filter((item) => !item.closest('[data-user-message-bubble]')); if (found.length) { return found; } } catch (error) { /* next selector */ }\n"
    "    }\n"
    "    return [];\n"
    "  };\n"
    "  list = messageNodes();\n"
    "  const index = __INDEX__;\n"
    "  const node = (index === null || index === undefined) ? list[list.length - 1] : list[index];\n"
    "  if (!node) { return ''; }\n"
    "  let body = null;\n"
    "  for (const entry of (REG.answer_body || [])) {\n"
    "    try { if (node.matches(entry[0])) { body = node; break; } body = node.querySelector(entry[0]); } catch (error) { body = null; }\n"
    "    if (body && !body.closest('[data-user-message-bubble]')) { break; }\n"
    "    body = null;\n"
    "  }\n"
    "  if (!body && (node.matches('[data-conversation-role=\\\"assistant\\\"]') || node.matches('[data-talvt-turn-state]'))) { const turn = node.matches('[data-talvt-turn-state]') ? node : (node.closest('[data-talvt-turn-state]') || node.parentElement); if (turn) { for (const entry of (REG.answer_body || [])) { try { body = turn.querySelector(entry[0]); if (body && !body.closest('[data-user-message-bubble]')) { break; } body = null; } catch (error) { body = null; } } } }\n"
    "  if (!body || body.closest('[data-user-message-bubble]')) { return ''; }\n"
    "  const text = (body.textContent || '').trim();\n"
    "  return /^(you said:|\\u0432\\u044b \\u0441\\u043a\\u0430\\u0437\\u0430\\u043b\\u0438:)/i.test(text) ? '' : text;\n"
    "})()"
)

# A *redacted* DOM skeleton, written to disk only when a run fails.
#
# The artifact exists to answer "did the selector still exist, and how was it
# nested", so it keeps tags, roles, test ids and class names and deliberately
# throws away:
#   * every <script>/<style>/<head> payload (Next.js ships the whole page state
#     inside inline scripts, including the conversation);
#   * every text node (the conversation, the draft prompt, sidebar titles);
#   * every attribute that is not on the allow-list below (auth tokens, csrf
#     nonces, session data and hrefs pointing at a conversation id);
#   * `aria-label`, which on the real site carries the account name and email.
DOM_JS = (
    "/*hybrid:dom*/\n"
    "(() => {\n"
    "  if (!document.documentElement) { return ''; }\n"
    "  const clone = document.documentElement.cloneNode(true);\n"
    "  clone.querySelectorAll('script, style, noscript, template, svg, iframe, link, meta, head')\n"
    "    .forEach((node) => node.remove());\n"
    "  const KEEP = /^(data-testid|data-message-author-role|data-message-id|role|id|type|class|contenteditable|disabled|aria-selected|aria-checked|aria-disabled|aria-haspopup|aria-expanded|data-state)$/i;\n"
    "  clone.querySelectorAll('*').forEach((node) => {\n"
    "    for (const attr of Array.from(node.attributes)) {\n"
    "      if (!KEEP.test(attr.name)) { node.removeAttribute(attr.name); }\n"
    "      else if (attr.value.length > 80) { node.setAttribute(attr.name, attr.value.slice(0, 80) + '...'); }\n"
    "    }\n"
    "  });\n"
    "  const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);\n"
    "  let textNode = walker.nextNode();\n"
    "  while (textNode) { textNode.nodeValue = ''; textNode = walker.nextNode(); }\n"
    "  return clone.outerHTML.slice(0, __LIMIT__);\n"
    "})()"
)


@lru_cache(maxsize=16)
def _profile_scripts(profile):
    """Build and cache probe scripts by immutable profile value."""
    default_registry = _registry_js()
    profile_registry = _registry_js(profile)
    state_full = STATE_JS.replace(default_registry, profile_registry)
    state_fast = STATE_FAST_JS.replace(default_registry, profile_registry)
    answer = ANSWER_JS.replace(default_registry, profile_registry)
    attribute = json.dumps(profile.turn_state_attribute)
    state_full = state_full.replace("'" + TURN_STATE_ATTRIBUTE + "'", attribute)
    state_fast = state_fast.replace("'" + TURN_STATE_ATTRIBUTE + "'", attribute)
    for name, pattern in (
        ("loginWall", profile.login_wall_re),
        ("captcha", profile.captcha_re),
        ("rateLimit", profile.rate_limit_re),
    ):
        context = {"loginWall": "headText", "captcha": "bodyText", "rateLimit": "bodyText"}[name]
        if name == "captcha":
            # Cloudflare's shell is present on ordinary DeepSeek pages too.
            # Only a visible overlay counts as structural evidence; hidden
            # placeholders and empty Turnstile mounts must not block the page.
            detected = (
                "(() => { const node = document.querySelector('#cf-overlay'); "
                "if (!node) return false; const style = getComputedStyle(node); "
                "return style.display !== 'none' && style.visibility !== 'hidden' "
                "&& node.getClientRects().length > 0; })()"
            )
            if pattern:
                detected = f"(new RegExp({json.dumps(pattern)}, 'i').test(bodyText) || {detected})"
        else:
            detected = f"new RegExp({json.dumps(pattern)}, 'i').test({context})" if pattern else "false"
        replacement = f"  const {name} = {detected};"
        start = f"  const {name} = /"
        lines = state_full.splitlines()
        for index, line in enumerate(lines):
            if line.startswith(start):
                lines[index] = replacement
                break
        state_full = "\n".join(lines)
    labels = json.dumps([label.lower() for label in profile.role_labels], ensure_ascii=False)
    state_full = state_full.replace(
        "return /^(you said:|\\u0432\\u044b \\u0441\\u043a\\u0430\\u0437\\u0430\\u043b\\u0438:)/i.test(text) ? '' : text;",
        f"return {labels}.some((label) => text.toLowerCase().includes(label)) ? '' : text;",
    )
    state_fast = state_fast.replace(
        "return /^(you said:|\\u0432\\u044b \\u0441\\u043a\\u0430\\u0437\\u0430\\u043b\\u0438:)/i.test(text) ? '' : text;",
        f"return {labels}.some((label) => text.toLowerCase().includes(label)) ? '' : text;",
    )
    answer = answer.replace(
        "return /^(you said:|\\u0432\\u044b \\u0441\\u043a\\u0430\\u0437\\u0430\\u043b\\u0438:)/i.test(text) ? '' : text;",
        f"return {labels}.some((label) => text.toLowerCase().includes(label)) ? '' : text;",
    )
    return state_full, state_fast, answer


def answer_js(index: int | None = None, profile=None) -> str:
    script = ANSWER_JS if profile is None else _profile_scripts(profile)[2]
    return script.replace("__INDEX__", "null" if index is None else str(int(index)))


def dom_js(limit: int = 120000) -> str:
    return DOM_JS.replace("__LIMIT__", str(int(limit)))


def selector_report(
    hits: dict,
    assistant_count: int = 0,
    stop_button: bool = False,
) -> list[str]:
    """Human-readable "why did it find / not find this element" lines."""
    lines: list[str] = []
    for name in (
        "composer",
        "send_button",
        "stop_button",
        "assistant_message",
        "answer_body",
        "message_key",
        "turn_state",
        "new_chat",
    ):
        query = (hits or {}).get(name)
        if query:
            lines.append(f"{name}: found by {query}")
        elif name == "assistant_message" and assistant_count:
            lines.append(f"{name}: {assistant_count} found (matched by fallback query)")
        else:
            lines.append(f"{name}: not found")
    lines.append(f"assistant messages: {assistant_count} found")
    lines.append(f"stop button: {'found' if stop_button else 'not found'}")
    return lines


# --- structured page state ---------------------------------------------------


@dataclass
class PageState:
    profile: str = "chatgpt"
    url: str = ""
    title: str = ""
    ready_state: str = ""
    # False when the cheap probe was used: the login wall / captcha / rate limit
    # signals were deliberately not read, so they must not be trusted as "no".
    signals_checked: bool = False
    signed_in: bool = False
    login_wall: bool = False
    captcha: bool = False
    rate_limit: bool = False
    composer: bool = False
    composer_chars: int = 0
    # Confidence of the selector that matched the composer. A low value means
    # only a last-resort fallback matched, which on a page that has not mounted
    # is exactly what a stale `textarea` looks like.
    composer_confidence: float = 0.0
    composer_head: str = ""
    composer_tail: str = ""
    composer_is_code_editor: bool = False
    send_button: bool = False
    send_enabled: bool = False
    stop_button: bool = False
    # Explicit generation state of the answer turn ("complete", "thinking", ...),
    # when the site provides one. None means "the build does not say".
    turn_state: str | None = None
    mode: str = "unknown"
    chat_mode_available: bool = False
    new_chat_button: bool = False
    assistant_count: int = 0
    assistant_keys: list[str] = field(default_factory=list)
    last_answer_key: str = ""
    last_answer_chars: int = 0
    last_answer_hash: str = ""
    last_answer_head: str = ""
    last_answer_tail: str = ""
    selector_hits: dict = field(default_factory=dict)
    selector_confidence: dict = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict, profile=None) -> "PageState":
        keys = raw.get("assistantKeys") or []
        return cls(
            profile=getattr(profile, "name", "chatgpt"),
            url=str(raw.get("url", "")),
            title=str(raw.get("title", "")),
            ready_state=str(raw.get("readyState", "")),
            signals_checked=bool(raw.get("signalsChecked")),
            signed_in=bool(raw.get("signedIn")),
            login_wall=bool(raw.get("loginWall")),
            captcha=bool(raw.get("captcha")),
            rate_limit=bool(raw.get("rateLimit")),
            composer=bool(raw.get("composer")),
            composer_confidence=float(raw.get("composerConfidence") or 0.0),
            composer_chars=int(raw.get("composerChars") or 0),
            composer_head=str(raw.get("composerHead", "")),
            composer_tail=str(raw.get("composerTail", "")),
            composer_is_code_editor=bool(raw.get("composerIsCodeEditor")),
            send_button=bool(raw.get("sendButton")),
            send_enabled=bool(raw.get("sendEnabled")),
            stop_button=bool(raw.get("stopButton")),
            turn_state=(str(raw["turnState"]) if raw.get("turnState") else None),
            mode=str(raw.get("mode", "unknown")),
            chat_mode_available=bool(raw.get("chatModeAvailable")),
            new_chat_button=bool(raw.get("newChatButton")),
            assistant_count=int(raw.get("assistantCount") or 0),
            assistant_keys=[str(key) for key in keys] if isinstance(keys, list) else [],
            last_answer_key=str(raw.get("lastAnswerKey", "")),
            last_answer_chars=int(raw.get("lastAnswerChars") or 0),
            last_answer_hash=str(raw.get("lastAnswerHash", "")),
            last_answer_head=str(raw.get("lastAnswerHead", "")),
            last_answer_tail=str(raw.get("lastAnswerTail", "")),
            selector_hits=dict(raw.get("selectorHits") or {}),
            selector_confidence=dict(raw.get("selectorConfidence") or {}),
        )

    # -- derived questions --------------------------------------------------

    def blockers(self) -> list[str]:
        """Reasons the automation cannot proceed, in the order worth reporting."""
        problems: list[str] = []
        if self.signals_checked:
            if self.login_wall:
                problems.append("not signed in (sign in once with `hybrid browser launch`)")
            if self.captcha:
                problems.append("human-verification challenge on the page")
            if self.rate_limit:
                problems.append("the site reports a usage limit")
        if self.composer_is_code_editor:
            problems.append(
                "the matched composer is a code editor (a Canvas answer), not the message box — "
                "typing would overwrite the answer's code"
            )
        if not self.composer:
            problems.append("no message composer found (page may still be loading)")
        return problems

    def fatal_blockers(self) -> list[str]:
        """Blockers where waiting longer cannot help, so the run fails fast.

        Only meaningful on a full probe: the cheap probe never reads the page
        text, so it cannot claim that there is no login wall.
        """
        problems: list[str] = []
        if self.composer_is_code_editor:
            # Never worth retrying: the selector matched the wrong editor.
            return [
                "the matched composer is a code editor (a Canvas answer), not the message box — "
                "refusing to type into the user's code"
            ]
        if not self.signals_checked:
            return []
        problems: list[str] = []
        if self.login_wall:
            problems.append("not signed in (sign in once with `hybrid browser launch`)")
        if self.captcha:
            problems.append("human-verification challenge on the page")
        if self.rate_limit:
            problems.append("the site reports a usage limit")
        return problems

    def can_submit(self) -> bool:
        return bool(self.composer and self.send_enabled and self.composer_chars)

    def turn_finished(self, profile=None) -> bool | None:
        """True/False when the site states the generation state, else None."""
        if not self.turn_state:
            return None
        value = self.turn_state.strip().lower()
        done = profile.turn_state_done if profile is not None else TURN_STATE_DONE
        running = profile.turn_state_running if profile is not None else TURN_STATE_RUNNING
        if value in done:
            return True
        if value in running:
            return False
        return None

    def turn_generating(self) -> bool:
        return self.turn_finished() is False

    def index_of(self, key: str) -> int | None:
        try:
            return self.assistant_keys.index(key)
        except ValueError:
            return None

    def to_dict(self, redact: bool = True) -> dict:
        """Serialise the state.

        ``redact=True`` (the default) is what gets written to disk: the full URL
        and the page title are replaced by a host, a coarse path shape and a
        title length. On ChatGPT `document.title` is the conversation name,
        auto-derived from the user's first message, so it must not be dropped
        into `state.json`/`timing.json` as-is. Interactive output that a human
        is reading right now can ask for ``redact=False``.
        """
        payload = {
            "url": self.url if not redact else self._redacted_url(),
            "profile": self.profile,
            "title": self.title if not redact else "",
            "title_length": len(self.title),
            "ready_state": self.ready_state,
            "signals_checked": self.signals_checked,
            "signed_in": self.signed_in,
            "login_wall": self.login_wall,
            "captcha": self.captcha,
            "rate_limit": self.rate_limit,
            "composer": self.composer,
            "composer_chars": self.composer_chars,
            "send_button": self.send_button,
            "send_enabled": self.send_enabled,
            "stop_button": self.stop_button,
            "turn_state": self.turn_state,
            "mode": self.mode,
            "chat_mode_available": self.chat_mode_available,
            "new_chat_button": self.new_chat_button,
            "assistant_count": self.assistant_count,
            "assistant_keys": self.assistant_keys[-12:],
            "last_answer_key": self.last_answer_key,
            "last_answer_chars": self.last_answer_chars,
            "last_answer_hash": self.last_answer_hash,
            "selector_hits": self.selector_hits,
            "selector_confidence": self.selector_confidence,
        }
        return payload

    def _redacted_url(self) -> str:
        try:
            from .sites import site_for_url

            return redact_url(self.url, site_for_url(self.url))
        except (ImportError, ValueError):
            return redact_url(self.url)

    def render(self) -> str:
        hits = self.selector_hits or {}
        composer_by = hits.get("composer") or "?"
        send_by = hits.get("send_button") or "?"
        signals = "checked" if self.signals_checked else "not read"
        state = self.turn_state or "-"
        return (
            f"url={self.url} mode={self.mode} signed_in={self.signed_in} signals={signals} "
            f"composer={self.composer}({self.composer_chars} by {composer_by}) "
            f"send={self.send_enabled}(by {send_by}) stop={self.stop_button} turn={state} "
            f"assistants={self.assistant_count} last={self.last_answer_chars}/{self.last_answer_hash}"
        )

    def report(self) -> list[str]:
        return selector_report(self.selector_hits, self.assistant_count, self.stop_button)


# --- tracing -----------------------------------------------------------------


@dataclass
class StageTiming:
    name: str
    start: float
    seconds: float

    def to_dict(self) -> dict:
        return {"stage": self.name, "start": round(self.start, 3), "seconds": round(self.seconds, 3)}


class RunTrace:
    """Wall-clock spans, selector hits, retries and the final page state."""

    def __init__(self) -> None:
        self.started = time.time()
        self.stages: list[StageTiming] = []
        self.selector_hits: dict = {}
        self.retries: list[dict] = []
        self.final_state: dict = {}
        self.notes: list[str] = []
        self._open: dict[str, float] = {}

    # -- spans --------------------------------------------------------------

    def begin(self, name: str) -> None:
        self._open[name] = time.time()

    def end(self, name: str) -> float:
        started = self._open.pop(name, time.time())
        seconds = time.time() - started
        self.stages.append(StageTiming(name, started - self.started, seconds))
        return seconds

    def mark(self, name: str, seconds: float = 0.0) -> None:
        """Record an instantaneous stage (a decision or an observation)."""
        self.stages.append(StageTiming(name, time.time() - self.started, seconds))

    def stage(self, name: str) -> "_TraceSpan":
        return _TraceSpan(self, name)

    # -- annotations --------------------------------------------------------

    def note_selectors(self, state: PageState) -> None:
        for name, query in (state.selector_hits or {}).items():
            if query:
                self.selector_hits.setdefault(name, query)

    def note_retry(self, stage: str, reason: str) -> None:
        self.retries.append({"stage": stage, "reason": reason, "at": round(time.time() - self.started, 3)})

    def note(self, message: str) -> None:
        self.notes.append(message)

    def finish(self, state: PageState | None = None) -> None:
        if state is not None:
            self.final_state = state.to_dict()

    def to_dict(self) -> dict:
        return {
            "stages": [stage.to_dict() for stage in self.stages],
            "total_seconds": round(time.time() - self.started, 2),
            "selector_hits": self.selector_hits,
            "retries": self.retries,
            "final_state": self.final_state,
            "notes": self.notes,
        }

    def render(self) -> str:
        if not self.stages:
            return "no timings recorded"
        lines = [f"{stage.name:<22} {stage.seconds:>6.2f}s (at {stage.start:>6.2f}s)" for stage in self.stages]
        lines.append(f"{'total':<22} {time.time() - self.started:>6.2f}s")
        return "\n".join(lines)


class _TraceSpan:
    def __init__(self, trace: RunTrace, name: str):
        self.trace = trace
        self.name = name

    def __enter__(self) -> RunTrace:
        self.trace.begin(self.name)
        return self.trace

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.trace.end(self.name)
        return False


# --- reading and waiting -----------------------------------------------------


class PageStateReader:
    """Reads the page once, waits for conditions adaptively, saves artifacts."""

    def __init__(
        self,
        page: ChromePage,
        fast: float = 0.15,
        mid: float = 0.5,
        slow: float = 1.5,
        profile=None,
    ):
        self.page = page
        if profile is None:
            from .sites import default_site

            profile = default_site()
        self.profile = profile
        # Adaptive polling schedule: fast while the page is reacting, slower
        # while the model is thinking, slowest during a long stream.
        self.fast = fast
        self.mid = mid
        self.slow = slow

    def read(self, fast: bool = False) -> PageState:
        """Read the page.

        ``fast=True`` uses the cheap probe, which never pulls page text into the
        process (so ``login_wall``/``captcha``/``rate_limit`` come back False and
        ``signals_checked`` is False). Use it on the hot path only; every
        diagnosis and every failure report must use the full probe.
        """
        full, quick, _ = _profile_scripts(self.profile)
        raw = self.page.eval(quick if fast else full)
        if not isinstance(raw, dict):
            raise CdpError("Page state probe returned nothing; the page may not be loaded")
        state = PageState.from_raw(raw, self.profile)
        if not self.profile.supports_turn_state:
            state.turn_state = None
        if not self.profile.supports_mode_tabs:
            state.mode = "unknown"
            state.chat_mode_available = False
        return state

    def answer_text(self, index: int | None = None, key: str | None = None) -> str:
        if key:
            state = self.read(fast=True)
            index = state.index_of(key)
        value = self.page.eval(answer_js(index, self.profile))
        return value if isinstance(value, str) else ""

    def dom_snippet(self, limit: int = 120000) -> str:
        """A redacted DOM skeleton: structure only, no text, no scripts."""
        value = self.page.eval(dom_js(limit), timeout=60.0)
        return value if isinstance(value, str) else ""

    def wait_ready(self, timeout: float = 30.0, fast: bool = False) -> PageState:
        """Wait until the page has rendered something worth diagnosing.

        ``document.readyState === 'complete'`` is satisfied by the server HTML
        long before a single-page app mounts, so a diagnostic taken straight
        after navigation describes an empty shell. Measured live: the same
        conversation that shows a 16 350-character answer reports zero messages
        when probed too early.

        The test is "the composer matched a selector we trust", not "some
        element matched something": on an un-hydrated shell even the last-resort
        `textarea` fallback can match, which makes a naive wait return instantly.

        Never raises: a diagnostic is still useful when the wait fails, so the
        last observed state is returned either way.
        """
        ready_confidence = 0.8
        try:
            return self.wait_until(
                lambda state: (
                    state.login_wall
                    or state.captcha
                    or (state.composer and state.composer_confidence >= ready_confidence)
                ),
                "the page to render",
                timeout=timeout,
                fast=fast,
            )
        except CdpError:
            return self.read(fast=fast)

    def wait_until(
        self,
        predicate,
        description: str,
        timeout: float = 30.0,
        interval: float | None = None,
        trace: RunTrace | None = None,
        fast: bool = False,
    ) -> PageState:
        """Poll fast at first, then back off; report the last state on timeout.

        Adaptive schedule: 150 ms for the first 10 s (page reactions are fast),
        500 ms up to 60 s (the model is thinking), then 1.5 s (long streams).
        """
        started = time.time()
        deadline = started + timeout
        last = PageState()
        attempts = 0
        while time.time() < deadline:
            last = self.read(fast=fast)
            attempts += 1
            if predicate(last):
                if trace is not None:
                    trace.note(f"{description}: satisfied after {attempts} probe(s)")
                return last
            waited = time.time() - started
            if interval is None:
                delay = self.fast if waited < 10 else (self.mid if waited < 60 else self.slow)
            else:
                delay = interval
            time.sleep(min(delay, max(0.0, deadline - time.time())))
        if trace is not None:
            trace.note(f"{description}: timed out after {attempts} probe(s)")
            trace.finish(last)
        raise CdpError(f"Timed out waiting for {description}. Last state: {last.render()}")

    def save_diagnostics(
        self,
        directory: Path,
        reason: str,
        stage: str,
        trace: RunTrace | None = None,
        state: PageState | None = None,
        dom_limit: int = 120000,
    ) -> Path:
        """Write everything needed to explain a failure after the fact.

        The bundle is bounded and deliberately low-content:

        * ``state.json``  - structured probe result, selector report, reason;
        * ``timing.json`` - per-stage wall clock from the run trace;
        * ``screenshot.png`` - what the page looked like (page pixels are not
          redactable, so this file may show the conversation);
        * ``dom-snippet.html`` - a *redacted* element skeleton: no text nodes,
          no ``<script>``/``<head>`` payloads, and only allow-listed attributes,
          capped at ``dom_limit`` characters.

        ``dom-snippet.html`` and ``screenshot.png`` are overwritten on every run
        of the same task, so a task directory cannot grow without bound.
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        if state is None:
            try:
                state = self.read()
            except CdpError:
                state = PageState()
        payload = {
            "stage": stage,
            "reason": reason,
            "state": state.to_dict(),
            "selector_report": state.report(),
            "artifacts": {
                "dom_snippet_redacted": True,
                "dom_snippet_max_chars": dom_limit,
                "screenshot_may_contain_page_content": True,
            },
        }
        (directory / "state.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if trace is not None:
            (directory / "timing.json").write_text(
                json.dumps(trace.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        try:
            self.page.screenshot(directory / "screenshot.png")
        except CdpError:
            pass
        try:
            snippet = self.dom_snippet(dom_limit)
            if snippet:
                (directory / "dom-snippet.html").write_text(snippet, encoding="utf-8", newline="\n")
        except CdpError:
            pass
        return directory / "state.json"
