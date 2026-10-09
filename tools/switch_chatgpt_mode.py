"""Switch the ChatGPT page between Chat and Work mode.

    python tools/switch_chatgpt_mode.py [chat|work]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge import chatgpt_ui
from hybrid.browser_bridge.session_live import BrowserSession
from hybrid.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="chat", choices=["chat", "work"])
    parser.add_argument("--url", default="https://chatgpt.com/")
    parser.add_argument("--shot", default=None)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        print(f"mode before: {chatgpt_ui.detect_mode(page)}")
        if args.mode == "work":
            print(f"clicked Work tab: {chatgpt_ui.click_tab(page, ('Работа', 'Work'))}")
        else:
            print(f"chat mode: {'active' if chatgpt_ui.ensure_chat_mode(page) else 'unavailable'}")
        print(f"mode after: {chatgpt_ui.detect_mode(page)}")
        if args.shot:
            shot = Path(args.shot)
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(shot)
            print(f"screenshot: {shot}")
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
