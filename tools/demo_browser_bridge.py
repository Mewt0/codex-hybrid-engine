"""End-to-end Browser AI Bridge demo (no network, no credentials).

Runs the relay workflow against `demo_project`:

    prepare -> simulated answer import -> patch validation -> review

The answer below stands in for the text a human would paste back from
DeepSeek Web / ChatGPT Web. Run:

    python tools/demo_browser_bridge.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("PYTHONPATH", str(PROJECT_ROOT))

from hybrid.browser_bridge import BrowserBridge
from hybrid.controller import Controller
from hybrid.config import load_settings


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)


def build_simulated_answer(project_dir: Path) -> str:
    """Ask git for a real diff so the demo never hardcodes line endings."""
    original = (project_dir / "app.js").read_text(encoding="utf-8")
    updated = original.replace('return "FIXED";', 'return "READY";')
    if updated == original:
        updated = original + '\nexport const panel = "ready";\n'
    with tempfile.TemporaryDirectory() as scratch:
        scratch_dir = Path(scratch) / "proj"
        shutil.copytree(project_dir, scratch_dir, ignore=shutil.ignore_patterns(".hybrid", ".git"))
        run(["git", "init", "-q"], scratch_dir)
        run(["git", "config", "user.email", "demo@example.invalid"], scratch_dir)
        run(["git", "config", "user.name", "Demo"], scratch_dir)
        run(["git", "add", "-A"], scratch_dir)
        run(["git", "commit", "-qm", "baseline"], scratch_dir)
        (scratch_dir / "app.js").write_text(updated, encoding="utf-8", newline="\n")
        diff = run(["git", "diff", "--", "app.js"], scratch_dir).stdout
    return SIMULATED_ANSWER_TEMPLATE.replace("{{PATCH}}", diff.replace("\r\n", "\n").rstrip("\n"))


SIMULATED_ANSWER_TEMPLATE = """## SUMMARY
Renamed the placeholder label and kept the existing module contract intact so
current importers keep working.

## FILES
- app.js — return "READY" from label() instead of "FIXED"

## PATCH
```diff
{{PATCH}}
```

## CHECKS
- `node --check app.js` passes
- Existing importers of the module keep working

## LIMITATIONS
- No browser run was possible in this environment.
"""


def ensure_demo_repo(project_dir: Path) -> bool:
    """The demo project is plain files in the repository; create its git repo."""
    if (project_dir / ".git").exists():
        return True
    if run(["git", "init", "-q"], project_dir).returncode != 0:
        print("Could not initialise the demo repository; is git installed?")
        return False
    run(["git", "config", "user.email", "demo@example.invalid"], project_dir)
    run(["git", "config", "user.name", "Demo"], project_dir)
    run(["git", "add", "-A"], project_dir)
    run(["git", "commit", "-qm", "demo baseline"], project_dir)
    return True


def main() -> int:
    project_dir = PROJECT_ROOT / "demo_project"
    if not ensure_demo_repo(project_dir):
        return 1

    settings = load_settings(project_dir)
    controller = Controller(settings)
    bridge = BrowserBridge(settings, controller)

    browser_task = bridge.prepare(
        "Улучши внешний вид игровой панели, сохрани существующие JavaScript-события и сделай интерфейс адаптивным",
        "deepseek_web",
        "frontend",
    )
    print("=== 1. Browser task prepared (nothing was sent anywhere) ===")
    print(f"browser task : {browser_task.task_id}")
    print(f"engine task  : {browser_task.engine_task_id}")
    print(f"provider     : {browser_task.provider}")
    print(f"profile      : {browser_task.profile}")
    print(f"skills       : {', '.join(browser_task.skills)}")
    print(f"prompt       : {browser_task.prompt_path}")

    prompt = bridge.prompt(browser_task.task_id)
    print(f"prompt chars : {len(prompt)}")
    print("prompt starts with:")
    print("\n".join(prompt.splitlines()[:6]))

    print("\n=== 2. Import the answer the human pasted back ===")
    answer = build_simulated_answer(project_dir)
    record = bridge.import_response(browser_task.task_id, answer)
    print(f"engine task  : {record.task_id}")
    print(f"status       : {record.status}")
    print(f"changed files: {', '.join(record.changed_files)}")
    for name, result in record.checks.items():
        print(f"  - {name}: {result['status']}")

    payload = bridge.review_payload(browser_task.task_id)
    print(f"review file  : {payload['response_path']}")
    print(f"apply with   : {payload['apply_command']}")

    print("\n=== 3. Diff under review ===")
    print(bridge.diff(browser_task.task_id))

    print("=== 4. Repeat import is refused ===")
    try:
        bridge.import_response(browser_task.task_id, answer)
        print("UNEXPECTED: second import was accepted")
    except Exception as exc:
        print(f"refused as expected: {type(exc).__name__}: {exc}")

    print("\n=== 5. Apply with explicit confirmation ===")
    if record.status == "ready_for_review":
        applied = controller.apply(record.task_id, confirm=True)
        print(f"status       : {applied.status}")
        print(f"app.js now   : {(project_dir / 'app.js').read_text(encoding='utf-8').strip().splitlines()[0]}")
    else:
        print(f"not applied; task status is {record.status}")

    print("\n=== 6. Reset the demo project ===")
    run(["git", "checkout", "--", "app.js"], project_dir)
    cleanup_worktrees(project_dir)
    print(f"app.js reset : {(project_dir / 'app.js').read_text(encoding='utf-8').strip()}")
    return 0


def cleanup_worktrees(project_dir: Path) -> None:
    """Drop demo worktrees so repeat runs stay reproducible."""
    listing = run(["git", "worktree", "list", "--porcelain"], project_dir).stdout
    for line in listing.splitlines():
        if not line.startswith("worktree "):
            continue
        path = Path(line.split(" ", 1)[1])
        if path.resolve() == project_dir.resolve():
            continue
        run(["git", "worktree", "remove", "--force", str(path)], project_dir)
    branches = run(["git", "branch", "--list", "hybrid/*"], project_dir).stdout
    for branch in branches.split():
        run(["git", "branch", "-D", branch], project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
