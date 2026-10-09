"""Keep ChatGPT in Chat mode, pick the strongest model and maximum effort.

Thin CLI wrapper: all of the UI knowledge lives in
``hybrid.browser_bridge.chatgpt_ui`` so the workflow and this script can never
drift apart.

    python tools/chatgpt_setup_chat_mode.py [--no-effort] [--shot PATH]
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
    parser.add_argument("--no-effort", action="store_true", help="do not touch the reasoning effort control")
    parser.add_argument("--shot", default=None, help="save a screenshot here (default .hybrid/diagnostics/)")
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        print(f"mode before: {chatgpt_ui.detect_mode(page)}")
        if chatgpt_ui.ensure_chat_mode(page):
            print("chat mode: active")
        else:
            print("chat mode: could NOT be selected (the tabs may not be present)")

        model = chatgpt_ui.select_best_model(page)
        print(f"model: {model or 'picker not found; leaving it as is'}")

        if not args.no_effort:
            effort = chatgpt_ui.set_effort_max(page)
            print(f"reasoning effort: {effort or 'no effort control found'}")

        report = chatgpt_ui.diagnose_ui(page)
        print(json.dumps(report, ensure_ascii=False, indent=2))

        shot = Path(args.shot) if args.shot else ROOT / ".hybrid" / "diagnostics" / "chatgpt-ui.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        print(f"screenshot: {shot} ({'saved' if page.screenshot(shot) else 'failed'})")
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
