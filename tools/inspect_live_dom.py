"""Report what the LIVE chat page actually looks like, to maintain the selectors.

ChatGPT (and every other web chat) rewrites its DOM without warning. When the
automation reports "the web chat never started answering" or "send button was
not available" while the answer is plainly on screen, run this against the page
and compare its output with the `SELECTORS` registry in
``hybrid/browser_bridge/browser_state.py``.

Structure only: this never prints message text.

    python tools/inspect_live_dom.py [conversation-url]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge.browser_state import PageStateReader
from hybrid.browser_bridge.cdp import ChromePage, CdpError
from hybrid.browser_bridge.sites import site_for_provider
from hybrid.config import load_settings

SIGNALS = """
/*hybrid:live-signals*/
(() => {
  const count = (query) => { try { return document.querySelectorAll(query).length; } catch (e) { return -1; } };
  const dataAttrs = new Set();
  document.querySelectorAll('*').forEach((node) => {
    for (const attr of node.attributes) { if (attr.name.startsWith('data-')) { dataAttrs.add(attr.name); } }
  });
  const labels = [];
  document.querySelectorAll('button, [role="button"]').forEach((node) => {
    const rect = node.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) { return; }
    const label = (node.getAttribute('aria-label') || node.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    if (label) { labels.push(label); }
  });
  return {
    url: location.href,
    title: document.title,
    readyState: document.readyState,
    counts: {
      proseMirror: count('.ProseMirror'),
      promptTextarea: count('#prompt-textarea'),
      contentEditables: count('[contenteditable="true"]'),
      messageRoleAttr: count('[data-message-author-role]'),
      assistantRoleAttr: count('[data-message-author-role="assistant"]'),
      article: count('article'),
      markdown: count('.markdown'),
      turnTestid: count('[data-testid^="conversation-turn"]'),
      sendByTestid: count('button[data-testid="send-button"]'),
      stopByTestid: count('button[data-testid="stop-button"]'),
      sendByAria: count('button[aria-label*="Отправ"]') + count('button[aria-label*="Send"]'),
      stopByAria: count('button[aria-label*="Останов"]') + count('button[aria-label*="Stop"]'),
      shadowHosts: Array.from(document.querySelectorAll('*')).filter((node) => node.shadowRoot).length,
    },
    mainTextLength: ((document.querySelector('main') || document.body).textContent || '').length,
    dataAttributes: Array.from(dataAttrs).sort().slice(0, 80),
    visibleButtonLabels: labels.slice(0, 50),
    candidates: Array.from(document.querySelectorAll('textarea, input, button, [role], [contenteditable="true"], article, main, section'))
      .filter((node) => (node.textContent || '').trim().length > 0 || node.matches('textarea, input, [contenteditable="true"], [role="textbox"]'))
      .slice(0, 60).map((node) => ({
        tag: node.tagName.toLowerCase(), role: node.getAttribute('role'),
        type: node.getAttribute('type'), cls: String(node.className || '').slice(0, 100),
        attrs: Array.from(node.attributes).filter((attr) => attr.name.startsWith('data-')).map((attr) => [attr.name, attr.value.slice(0, 40)]),
        textLen: (node.textContent || '').length,
        head: (node.textContent || '').trim().slice(0, 60).replace(/\\s+/g, ' '),
      })),
    challenge: !!document.querySelector('#cf-turnstile, [name="cf-turnstile-response"]'),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://chatgpt.com/")
    parser.add_argument("--site", default="chatgpt", help="registered site profile (chatgpt or deepseek)")
    parser.add_argument("--settle", type=float, default=2.0, help="seconds to let the SPA mount")
    parser.add_argument("--shot", default=None)
    args = parser.parse_args()

    try:
        profile = site_for_provider(args.site)
    except ValueError as exc:
        parser.error(str(exc))

    settings = load_settings(ROOT)
    port = int(dict(settings.raw.get("browser_session", {})).get("port", 9333))
    page = ChromePage(port=port)
    try:
        page.connect_page()
    except CdpError as exc:
        print(f"ERROR: no shared session on port {port}: {exc}")
        print("Start it with `hybrid browser launch`.")
        return 1

    reader = PageStateReader(page, fast=0.25, mid=0.5, slow=1.0, profile=profile)
    try:
        current_url = str(page.eval("location.href") or "")
        if current_url.rstrip("/") != args.url.rstrip("/"):
            page.navigate(args.url)
        # readyState is not "the SPA has mounted": wait for something real.
        try:
            reader.wait_until(
                lambda state: state.composer or state.login_wall or state.captcha,
                "the page to render",
                timeout=30,
                fast=False,
            )
        except CdpError as exc:
            print(f"warning: {exc}")
        time.sleep(args.settle)

        state = reader.read()
        print("page state (full probe):")
        print(f"  {state.render()}")
        print("selector report:")
        for line in state.report():
            print(f"  {line}")
        print("selector confidence:")
        for name, score in state.selector_confidence.items():
            print(f"  {name}: {score:.2f}")

        print("live DOM signals:")
        print(json.dumps(page.eval(SIGNALS), ensure_ascii=False, indent=2))

        print("verdict:")
        hits = state.selector_hits
        for name in ("composer", "send_button", "assistant_message", "stop_button"):
            print(f"  {name}: {'OK via ' + hits[name] if hits.get(name) else 'NOT FOUND'}")

        if args.shot:
            shot = Path(args.shot)
            shot.parent.mkdir(parents=True, exist_ok=True)
            print(f"screenshot: {shot} ({'saved' if page.screenshot(shot) else 'failed'})")
        return 0
    except CdpError as exc:
        print(f"ERROR: {exc}")
        return 2
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
