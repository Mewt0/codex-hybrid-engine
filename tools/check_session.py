"""Check whether the shared Chrome session is signed in (read-only).

    python tools/check_session.py [url]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hybrid.browser_bridge.session_live import BrowserSession
from hybrid.config import load_settings

CHECK = """
(() => {
  const box = document.querySelector('#prompt-textarea, textarea, [contenteditable="true"]');
  const text = (document.body.innerText || '').slice(0, 4000);
  const loginCta = /log in|sign up|войти|зарегистр/i.test(text);
  const profileBtn = document.querySelector('[data-testid="profile-button"], button[aria-label*="Профиль"], button[aria-label*="Profile"]');
  return {
    title: document.title,
    url: location.href,
    hasComposer: !!box,
    loginCta,
    hasProfileButton: !!profileBtn,
    signedIn: !!box && !loginCta,
  };
})()
"""


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "https://chatgpt.com/"
    settings = load_settings(ROOT)
    session = BrowserSession(settings)
    state = session.state()
    print(f"session running: {state.running} port={state.port}")
    if not state.running:
        print("start it with: hybrid browser launch")
        return 1

    page = session.open_page(url)
    try:
        info = page.eval(CHECK)
        for key, value in (info or {}).items():
            print(f"{key}: {value}")
        shot = ROOT / ".session-check.png"
        if page.screenshot(shot):
            print(f"screenshot: {shot} ({shot.stat().st_size} bytes)")
        return 0 if (info or {}).get("signedIn") else 2
    finally:
        page.close()


if __name__ == "__main__":
    raise SystemExit(main())
