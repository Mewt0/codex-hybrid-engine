"""Print what the ChatGPT page currently shows (diagnostic).

Uses the shared page probe, so this dump and the automation can never disagree
about what "the composer", "the send button" or "an assistant message" means.

    python tools/chat_state.py [--json] [--save-answer PATH]
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://chatgpt.com/")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--save-answer", default=None)
    parser.add_argument("--shot", default=None)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        reader = PageStateReader(page)
        state = reader.read()
        if args.json:
            print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(state.render())
            for line in state.report():
                print(f"  {line}")
            for blocker in state.blockers():
                print(f"  BLOCKER: {blocker}")

        shot = Path(args.shot) if args.shot else ROOT / ".hybrid" / "diagnostics" / "chat-state.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        print(f"screenshot: {shot} ({'saved' if page.screenshot(shot) else 'failed'})")

        if args.save_answer:
            answer = reader.answer_text()
            target = Path(args.save_answer)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(answer, encoding="utf-8", newline="\n")
            print(f"last answer saved: {target} ({len(answer)} chars)")
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
