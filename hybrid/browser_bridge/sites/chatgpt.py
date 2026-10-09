"""ChatGPT-specific UI control: mode, model, reasoning effort, diagnostics.

Everything the automation knows about *this* site lives here, so the tools in
``tools/chatgpt_*.py`` stay thin CLI wrappers and no workflow has to re-derive
"which button is the model picker" for itself.

Every JS probe carries a ``/*hybrid:ui:...*/`` marker so tests can drive the
whole module with a fake page. Each helper returns a plain value or ``None``;
none of them raise on a missing element, because the caller decides whether a
missing picker is fatal (it usually is not).
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

from ..browser_state import PageState, PageStateReader, Selector, SELECTORS
from ..cdp import ChromePage, CdpError

# Locale-proof labels: the picker text differs per language, so accept both.
EFFORT_LABEL_RE = r"High|Medium|Low|Extra|Instant|Pro|Auto|Высок|Средн|Низк|Минимал|Максим"

# Best-first model preference. The first label that exists in the menu wins.
# Kept as data so a new model is a one-line change, not a code change.
MODEL_PREFERENCE = (
    "GPT-5.5 Pro",
    "GPT-5.5 Thinking",
    "GPT-5.5",
    "GPT-5 Pro",
    "GPT-5 Thinking",
    "GPT-5",
    "o3-pro",
    "o3",
    "GPT-4.5",
    "GPT-4o",
)

EFFORT_PREFERENCE = ("Максимум", "Максимально", "Высокий", "Высоко", "Extra High", "High", "Maximum", "Max")

TAB_CLICK_JS = """
/*hybrid:ui:click-tab*/
((label) => {
  const nodes = Array.from(document.querySelectorAll('[role="tab"], button, [role="button"]'));
  const hit = nodes.find((node) => {
    const text = (node.innerText || node.getAttribute('aria-label') || '').trim();
    const rect = node.getBoundingClientRect();
    return text === label && rect.width > 2 && rect.height > 2;
  });
  if (!hit) { return false; }
  hit.click();
  return true;
})(__LABEL__)
"""

MODEL_PICKER_JS = """
/*hybrid:ui:model-picker*/
(() => {
  const nodes = Array.from(document.querySelectorAll('button, [role="button"]'));
  const hit = nodes.find((node) => {
    const text = (node.innerText || '').trim();
    return new RegExp('^(?:__EFFORT__)').test(text);
  });
  if (!hit) { return null; }
  const rect = hit.getBoundingClientRect();
  return {label: (hit.innerText || '').trim().split('\\n')[0], x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2)};
})()
"""

OPEN_MENU_JS = """
/*hybrid:ui:open-menu*/
(() => {
  const nodes = Array.from(document.querySelectorAll('button, [role="button"]'));
  const hit = nodes.find((node) => new RegExp('^(?:__EFFORT__)').test((node.innerText || '').trim()));
  if (!hit) { return false; }
  hit.click();
  return true;
})()
"""

MENU_ITEMS_JS = """
/*hybrid:ui:menu-items*/
(() => {
  const root = document.querySelector('[data-radix-popper-content-wrapper], [role="menu"], [role="dialog"], [role="listbox"]');
  if (!root) { return []; }
  const out = [];
  const nodes = root.querySelectorAll('[role="menuitemradio"], [role="menuitem"], [role="option"], button');
  nodes.forEach((node) => {
    const rect = node.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) { return; }
    const label = (node.innerText || '').trim().replace(/\\s+/g, ' ');
    if (!label) { return; }
    out.push({
      label,
      role: node.getAttribute('role') || '',
      checked: node.getAttribute('aria-checked') || node.getAttribute('aria-selected') || '',
      disabled: !!node.disabled,
      x: Math.round(rect.x + rect.width / 2),
      y: Math.round(rect.y + rect.height / 2),
    });
  });
  return out;
})()
"""

CLICK_MENU_ITEM_JS = """
/*hybrid:ui:click-menu-item*/
((wanted) => {
  const root = document.querySelector('[data-radix-popper-content-wrapper], [role="menu"], [role="dialog"], [role="listbox"]') || document;
  const nodes = Array.from(root.querySelectorAll('[role="menuitemradio"], [role="menuitem"], [role="option"], button'));
  const hit = nodes.find((node) => {
    const rect = node.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2 || node.disabled) { return false; }
    const label = (node.innerText || '').trim().replace(/\\s+/g, ' ');
    return label === wanted || label.startsWith(wanted);
  });
  if (!hit) { return false; }
  hit.click();
  return true;
})(__LABEL__)
"""

EFFORT_SLIDER_JS = """
/*hybrid:ui:effort-slider*/
(() => {
  const nodes = Array.from(document.querySelectorAll('input[type="range"], [role="slider"]'));
  const node = nodes.find((candidate) => {
    const rect = candidate.getBoundingClientRect();
    return rect.width > 2 && rect.height > 2;
  });
  if (!node) { return null; }
  const rect = node.getBoundingClientRect();
  const value = (node.value !== undefined && node.value !== null) ? node.value : node.getAttribute('aria-valuenow');
  const max = (node.max !== undefined && node.max !== null) ? node.max : node.getAttribute('aria-valuemax');
  return {
    value: value === null || value === undefined ? null : String(value),
    max: max === null || max === undefined ? null : String(max),
    x: Math.round(rect.x),
    y: Math.round(rect.y + rect.height / 2),
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  };
})()
"""


def _js(template: str, **values) -> str:
    text = template
    for key, value in values.items():
        text = text.replace(f"__{key.upper()}__", json.dumps(value, ensure_ascii=False))
    return text


def _eval(page: ChromePage, expression: str, timeout: float = 20.0):
    """Evaluate a probe.

    A missing element is *not* an error: the probes return ``false``/``null``/
    ``[]`` for "not found", so no exception is raised in that case. Any
    ``CdpError`` therefore means the page could not be reached at all, and it is
    propagated instead of being flattened into "the control does not exist" —
    otherwise a dead connection looks exactly like a site redesign.
    """
    return page.eval(expression, timeout=timeout)


def _eval_quiet(page: ChromePage, expression: str, timeout: float = 20.0):
    """Same, but for purely cosmetic probes where a failure is not actionable."""
    try:
        return _eval(page, expression, timeout=timeout)
    except CdpError:
        return None


# --- mode --------------------------------------------------------------------


def detect_mode(page: ChromePage) -> str:
    """'chat', 'work' or 'unknown' (the chat/work tabs are not always present)."""
    state = PageStateReader(page).read()
    return state.mode


def click_tab(page: ChromePage, labels: tuple[str, ...] | list[str]) -> bool:
    """Click the first mode tab whose visible label matches, in either locale."""
    for label in labels:
        if _eval(page, _js(TAB_CLICK_JS, label=label)):
            return True
    return False


def ensure_chat_mode(page: ChromePage, timeout: float = 15.0) -> bool:
    """Leave Work mode for Chat mode. True when Chat mode is active afterwards."""
    reader = PageStateReader(page)
    state = reader.read()
    if state.mode != "work":
        return True
    if click_tab(page, ("Чат", "Chat")):
        try:
            reader.wait_until(lambda current: current.mode != "work", "chat mode", timeout=timeout)
            return True
        except CdpError:
            pass
    return reader.read().mode != "work"


# --- model picker ------------------------------------------------------------


def detect_model_picker(page: ChromePage) -> dict | None:
    """The currently selected model/effort label and where it is on screen."""
    value = _eval(page, _js(MODEL_PICKER_JS, effort=EFFORT_LABEL_RE))
    return value if isinstance(value, dict) else None


def open_model_menu(page: ChromePage) -> bool:
    return bool(_eval(page, _js(OPEN_MENU_JS, effort=EFFORT_LABEL_RE)))


def menu_items(page: ChromePage) -> list[dict]:
    value = _eval(page, MENU_ITEMS_JS)
    return value if isinstance(value, list) else []


def close_menu(page: ChromePage) -> None:
    _eval_quiet(page, "/*hybrid:ui:close-menu*/ (() => { document.body.click(); return true; })()")


def select_best_model(page: ChromePage, timeout: float = 10.0) -> str | None:
    """Open the model menu and pick the strongest model that is offered."""
    if not open_model_menu(page):
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = menu_items(page)
        labels = [str(item.get("label", "")) for item in items]
        for wanted in MODEL_PREFERENCE:
            for label in labels:
                if label == wanted or label.startswith(wanted):
                    if _eval(page, _js(CLICK_MENU_ITEM_JS, label=label)):
                        return label
        if labels:
            break
        time.sleep(0.2)
    close_menu(page)
    return None


# --- reasoning effort --------------------------------------------------------


def detect_effort(page: ChromePage) -> str | None:
    picker = detect_model_picker(page)
    return picker.get("label") if picker else None


def set_effort_max(page: ChromePage, timeout: float = 15.0) -> str | None:
    """Set the reasoning effort to its maximum, by menu entry or by slider.

    Returns the label that ended up selected, or ``None`` when the control is
    not present (older layouts simply have no effort control).
    """
    if not open_model_menu(page):
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = menu_items(page)
        for wanted in EFFORT_PREFERENCE:
            for item in items:
                label = str(item.get("label", ""))
                if item.get("disabled"):
                    continue
                if label == wanted or label.startswith(wanted):
                    if _eval(page, _js(CLICK_MENU_ITEM_JS, label=label)):
                        return label
        if items:
            break
        time.sleep(0.2)

    slider = _eval(page, EFFORT_SLIDER_JS)
    if isinstance(slider, dict) and slider.get("width"):
        # Drag the handle to the far right: the maximum effort position.
        y = int(slider["y"])
        start_x = int(slider["x"]) + int(int(slider["width"]) * 0.5)
        end_x = int(slider["x"]) + int(slider["width"]) - 2
        for event_type, x in (("mousePressed", start_x), ("mouseMoved", end_x), ("mouseReleased", end_x)):
            try:
                page.call(
                    "Input.dispatchMouseEvent",
                    {"type": event_type, "x": x, "y": y, "button": "left", "clickCount": 1},
                    timeout=15,
                )
            except CdpError:
                return None
            time.sleep(0.15)
        close_menu(page)
        return detect_effort(page)
    close_menu(page)
    return None


# --- diagnostics -------------------------------------------------------------


def diagnose_ui(page: ChromePage) -> dict:
    """One snapshot of the ChatGPT chrome: mode, model picker, effort, blockers."""
    state = PageStateReader(page).read()
    picker = detect_model_picker(page)
    return {
        "url": state.url,
        "title": state.title,
        "mode": state.mode,
        "chat_mode_available": state.chat_mode_available,
        "model_picker": picker.get("label") if picker else None,
        "effort": picker.get("label") if picker else None,
        "composer": state.composer,
        "send_enabled": state.send_enabled,
        "assistant_count": state.assistant_count,
        "blockers": state.blockers(),
        "selector_report": state.report(),
    }


def new_conversation(page: ChromePage, base_url: str = "https://chatgpt.com/", timeout: float = 30.0) -> PageState:
    """Open a fresh, empty conversation and prove it is empty.

    Navigating to the site root starts a new conversation; we then verify that
    the composer is empty and no assistant message is present, so a stale chat
    can never silently absorb the prompt. The wait polls the cheap probe (no
    page text) and takes a full probe once the page looks ready.
    """
    reader = PageStateReader(page)
    before = None
    try:
        before = reader.read().url
    except CdpError:
        pass
    page.navigate(base_url)

    def ready(current: PageState) -> bool:
        return current.composer and current.ready_state == "complete"

    def empty(current: PageState) -> bool:
        return ready(current) and current.assistant_count == 0

    state = reader.wait_until(ready, "composer on a new conversation", timeout=timeout, fast=True)
    if state.assistant_count:
        # A reused tab may still show the previous conversation; reload once.
        page.navigate(base_url)
        state = reader.wait_until(empty, "empty new conversation", timeout=timeout, fast=True)

    # One full probe at the end: the cheap probe cannot see a login wall, and
    # "the page is ready" must not be reported on unchecked signals.
    state = reader.read()
    blocked = state.fatal_blockers()
    if blocked:
        raise CdpError("cannot use this page as a new conversation: " + "; ".join(blocked))
    if state.composer_chars:
        raise CdpError(
            f"New conversation still has {state.composer_chars} characters in the composer"
            + (f" (was {before})" if before else "")
        )
    return state


def archive_conversation(page: ChromePage, conversation_url: str, timeout: float = 10.0) -> bool:
    """Archive exactly one ChatGPT conversation through its sidebar menu.

    The caller must only use this for a conversation created by the current
    automation run. Existing/continued conversations are never inferred as
    cleanup candidates. The URL is validated and matched against the exact
    sidebar link before opening its menu.
    """
    parsed = urlparse(conversation_url)
    if parsed.scheme != "https" or parsed.hostname != "chatgpt.com":
        raise CdpError("refusing to archive a conversation outside chatgpt.com")
    if not re.fullmatch(r"/c/[A-Za-z0-9_-]+", parsed.path):
        raise CdpError("refusing to archive a URL that is not one ChatGPT conversation")
    path_json = json.dumps(parsed.path)
    row_expression = (
        "(() => {"
        f"const path = {path_json};"
        "const link = Array.from(document.querySelectorAll('a[href]')).find((item) => {"
        "try { return new URL(item.href).pathname === path; } catch (error) { return false; }"
        "});"
        "const row = link && link.closest('[role=group]');"
        "const button = row && row.querySelector('button[aria-haspopup=menu]');"
        "if (!button) return null;"
        "const rect = button.getBoundingClientRect();"
        "return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, "
        "buttonId: button.id, menuId: button.getAttribute('aria-controls')};"
        "})()"
    )
    target = page.eval(row_expression)
    if not isinstance(target, dict):
        return False
    for event in ("mouseMoved", "mousePressed", "mouseReleased"):
        page.call(
            "Input.dispatchMouseEvent",
            {"type": event, "x": target["x"], "y": target["y"], "button": "left", "clickCount": 1},
        )
    menu_id_json = json.dumps(target.get("menuId"))
    if not target.get("menuId"):
        raise CdpError("the conversation action button did not identify its menu")
    menu_open_expression = (
        "(() => {const button = document.getElementById(" + json.dumps(target.get("buttonId")) + ");"
        "const menu = document.getElementById(" + menu_id_json + ");"
        "return !!button && button.getAttribute('aria-expanded') === 'true' && !!menu && menu.getAttribute('role') === 'menu';})()"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.eval(menu_open_expression):
            break
        time.sleep(0.1)
    else:
        raise CdpError("the exact conversation menu did not open; it was not archived")

    menu_expression = (
        "(() => {const menu = document.getElementById(" + menu_id_json + ");"
        "if (!menu || menu.getAttribute('role') !== 'menu') return null;"
        "const item = menu && Array.from(menu.querySelectorAll('[role=menuitem]')).find((node) => {"
        "const text = (node.innerText || node.getAttribute('aria-label') || '').trim();"
        "return /^(archive|archive chat|\\u0430\\u0440\\u0445\\u0438\\u0432\\u0438\\u0440\\u043e\\u0432\\u0430\\u0442\\u044c)$/i.test(text);"
        "}); if (!item) return null; const rect = item.getBoundingClientRect();"
        "return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};})()"
    )
    item = page.eval(menu_expression)
    if not isinstance(item, dict):
        page.eval("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))")
        raise CdpError("the conversation menu has no recognised Archive action; nothing was changed")
    for event in ("mouseMoved", "mousePressed", "mouseReleased"):
        page.call(
            "Input.dispatchMouseEvent",
            {"type": event, "x": item["x"], "y": item["y"], "button": "left", "clickCount": 1},
        )

    verify_expression = (
        "(() => !Array.from(document.querySelectorAll('a[href]')).some((link) => {"
        f"try {{ return new URL(link.href).pathname === {path_json}; }} catch (error) {{ return false; }}"
        "}))()"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.eval(verify_expression):
            return True
        time.sleep(0.1)
    raise CdpError("the conversation still appears in the sidebar after the Archive action")


from . import SiteProfile


def _archive_through_compatibility_module(page, conversation_url, timeout=10.0):
    """Keep monkeypatches/importers of the one-release facade effective."""
    from .. import chatgpt_ui

    return chatgpt_ui.archive_conversation(page, conversation_url)

CHATGPT = SiteProfile(
    name="chatgpt",
    display_name="ChatGPT",
    hostnames=("chatgpt.com",),
    new_conversation_url="https://chatgpt.com/",
    conversation_url_re=re.compile(r"^/c/[A-Za-z0-9_-]+/?$"),
    selectors=dict(SELECTORS),
    supports_turn_state=True,
    supports_effort=True,
    supports_mode_tabs=True,
    supports_archive=True,
    turn_state_attribute="data-talvt-turn-state",
    turn_state_done=frozenset({"complete", "completed", "done", "finished"}),
    turn_state_running=frozenset({"thinking", "streaming", "generating", "in_progress", "inprogress", "pending", "searching", "running"}),
    role_labels=("You said:", "Вы сказали:", "ChatGPT said:", "ChatGPT сказал:"),
    login_wall_re=r"log in|sign up|войти|зарегистр",
    captcha_re=r"verify you are human|проверка.*человек|captcha|cloudflare",
    rate_limit_re=r"too many requests|rate limit|лимит.*сообщен|usage limit",
    composer_exclude_classes=("cm-content", "cm-editor", "CodeMirror"),
    detect_effort=detect_effort,
    new_conversation=new_conversation,
    archive_conversation=_archive_through_compatibility_module,
)
