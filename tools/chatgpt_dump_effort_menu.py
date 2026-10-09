"""Open the ChatGPT model/effort menu and dump its structure (debugging aid).

Thin CLI wrapper over ``hybrid.browser_bridge.chatgpt_ui``.

    python tools/chatgpt_dump_effort_menu.py [--html PATH]
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
    parser.add_argument("--html", default=None, help="write the menu HTML here")
    args = parser.parse_args()

    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    page = session.open_page(args.url)
    try:
        print("opened menu:", chatgpt_ui.open_model_menu(page))
        items = chatgpt_ui.menu_items(page)
        print(f"menu items: {len(items)}")
        for item in items:
            print(
                f"  [{item['role']}] '{item['label']}' checked={item['checked']!r} "
                f"disabled={item['disabled']} at ({item['x']},{item['y']})"
            )
        print(json.dumps(chatgpt_ui.diagnose_ui(page), ensure_ascii=False, indent=2))
        if args.html:
            target = Path(args.html)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(page.eval("document.body.outerHTML") or "", encoding="utf-8", newline="\n")
            print(f"html: {target}")
        return 0
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
