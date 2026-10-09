"""Set the ChatGPT reasoning effort to its maximum (Chat mode).

Thin CLI wrapper over ``hybrid.browser_bridge.chatgpt_ui.set_effort_max``.

    python tools/chatgpt_max_effort.py [--shot PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge import chatgpt_ui
from hybrid.browser_bridge.session_live import BrowserSession
from hybrid.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://chatgpt.com/")
    parser.add_argument("--shot", default=None)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        print(f"mode: {chatgpt_ui.detect_mode(page)}")
        chatgpt_ui.ensure_chat_mode(page)

        effort = chatgpt_ui.set_effort_max(page)
        print(f"reasoning effort: {effort or 'no effort control found'}")
        print(json.dumps(chatgpt_ui.diagnose_ui(page), ensure_ascii=False, indent=2))

        shot = Path(args.shot) if args.shot else ROOT / ".hybrid" / "diagnostics" / "chatgpt-effort.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        print(f"screenshot: {shot} ({'saved' if page.screenshot(shot) else 'failed'})")
        return 0 if effort else 1
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
