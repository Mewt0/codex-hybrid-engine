"""Inspect the ChatGPT page: mode, model picker, composer and selector hits.

    python tools/probe_chatgpt_ui.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge import chatgpt_ui
from hybrid.browser_bridge.browser_state import PageStateReader
from hybrid.browser_bridge.session_live import BrowserSession
from hybrid.config import load_settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://chatgpt.com/")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--shot", default=None)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        state = PageStateReader(page).read()
        payload = {**chatgpt_ui.diagnose_ui(page), "state": state.to_dict()}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(state.render())
            print("Selectors:")
            for line in state.report():
                print(f"  {line}")
            print(f"Model picker: {payload['model_picker'] or 'not found'}")
            for blocker in payload["blockers"]:
                print(f"  BLOCKER: {blocker}")
        if args.shot:
            shot = Path(args.shot)
            shot.parent.mkdir(parents=True, exist_ok=True)
            print(f"screenshot: {shot} ({'saved' if page.screenshot(shot) else 'failed'})")
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
