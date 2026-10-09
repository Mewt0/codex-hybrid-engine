"""Dump the raw ChatGPT DOM shape when the shared probe finds nothing.

    python tools/chat_dump.py [--shot PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge.browser_state import PageStateReader
from hybrid.browser_bridge.session_live import BrowserSession
from hybrid.config import load_settings

SHAPE = """
/*hybrid:shape*/
(() => {
  const count = (query) => { try { return document.querySelectorAll(query).length; } catch (e) { return -1; } };
  const text = (document.body ? document.body.textContent : '').replace(/\\s+/g, ' ');
  return {
    url: location.href,
    title: document.title,
    readyState: document.readyState,
    articles: count('article'),
    roles: count('[data-message-author-role]'),
    assistants: count('[data-message-author-role="assistant"]'),
    contentEditables: count('[contenteditable="true"]'),
    textareas: count('textarea'),
    sendButtons: count('button[data-testid="send-button"]'),
    stopButtons: count('button[data-testid="stop-button"]'),
    markdownBlocks: count('.markdown'),
    bodyHead: text.slice(0, 300),
  };
})()
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://chatgpt.com/")
    parser.add_argument("--shot", default=None)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        reader = PageStateReader(page)
        print(json.dumps(reader.read().to_dict(), ensure_ascii=False, indent=2))
        print("raw shape:")
        print(json.dumps(page.eval(SHAPE), ensure_ascii=False, indent=2))

        shot = Path(args.shot) if args.shot else ROOT / ".hybrid" / "diagnostics" / "chat-dump.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        print(f"screenshot: {shot} ({'saved' if page.screenshot(shot) else 'failed'})")
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
