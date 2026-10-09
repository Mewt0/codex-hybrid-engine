from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from .config import load_settings, write_example_config
from .controller import Controller
from .providers.codex import CodexProvider
from .providers.groq import GroqProvider
from .providers.openrouter import OpenRouterProvider
from .quality.checks import php_binary
from .integrations.deepseek_harness import DeepSeekHarnessAdapter
from .integrations.codex_cli_delegate import CodexCliDelegate, result_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hybrid")
    parser.add_argument("--project", default=".", help="project directory")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("init")
    providers_parser = sub.add_parser("providers")
    providers_parser.add_argument("--json", action="store_true", help="machine-readable provider status")
    ui = sub.add_parser("ui")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    context = sub.add_parser("context")
    context_sub = context.add_subparsers(dest="context_cmd", required=True)
    context_sub.add_parser("preview")
    context_sub.add_parser("show")
    context_explain = context_sub.add_parser(
        "explain", help="why these files, in this order, for this task"
    )
    context_explain.add_argument("--task", required=True, help="the task description to explain")
    context_explain.add_argument("--profile", default=None)
    context_explain.add_argument("--json", action="store_true")
    context_explain.add_argument(
        "--no-repo-map",
        action="store_true",
        help="explain the extension-only ordering, without the repository map",
    )
    context_pack = context_sub.add_parser("pack", help="build a complete prompt pack for a web chat")
    context_pack.add_argument("task", help="task description")
    context_pack.add_argument("--profile", default=None)
    context_pack.add_argument("--files", default=None, help="comma separated project-relative files")
    context_pack.add_argument("--out", default=None, help="write the pack here (default .hybrid/prompt-pack.md)")
    skills_parser = sub.add_parser("skills")
    skills_parser.add_argument("--pack", action="store_true", help="print the assembled context pack for a task")
    profile_parser = sub.add_parser("profile")
    profile_parser.add_argument("--task", default=None, help="show the profile chosen for this description")
    browser = sub.add_parser("browser")
    browser_sub = browser.add_subparsers(dest="browser_cmd", required=True)
    browser_sub.add_parser("providers")
    browser_sub.add_parser("history")
    browser_prepare = browser_sub.add_parser("prepare")
    browser_prepare.add_argument("task")
    browser_prepare.add_argument("--provider", default="deepseek_web")
    browser_prepare.add_argument("--profile", default=None)
    for name in ("prompt", "open", "diff", "review", "cancel"):
        sub_parser = browser_sub.add_parser(name)
        sub_parser.add_argument("task_id")
    browser_import = browser_sub.add_parser("import")
    browser_import.add_argument("task_id")
    browser_import.add_argument("--file", default=None)
    browser_import.add_argument("--text", default=None, help="answer text inline")
    browser_import.add_argument("--force", action="store_true")
    browser_review_request = browser_sub.add_parser("request-review")
    browser_review_request.add_argument("task_id")
    browser_review_request.add_argument("--reviewer", default=None)
    browser_launch = browser_sub.add_parser("launch")
    browser_launch.add_argument("--url", default=None, help="page to open in the shared session")
    browser_sub.add_parser("status")
    browser_at = browser_sub.add_parser("at")
    browser_at.add_argument("--url", default=None)
    browser_at.add_argument("--check", default=None, help="JS expression returning a value to print")
    browser_at.add_argument("--shot", default=None, help="save a screenshot to this path")
    browser_say = browser_sub.add_parser("say")
    browser_say.add_argument("--url", default=None)
    browser_say.add_argument("--send", action="store_true", help="actually submit the message")
    browser_say.add_argument("--file", default=None, help="read the message from this file")
    browser_say.add_argument("--shot", default=None, help="save a screenshot after typing")
    browser_say.add_argument("text", nargs="?", default=None, help="message text; omit to read a task prompt")
    browser_say.add_argument("--task", default=None, help="prepare/read the prompt of this BTASK-ID")
    browser_chat = browser_sub.add_parser("chat", help="send a prompt to the live web chat and import the answer")
    browser_chat.add_argument("--url", default=None, help="conversation or site URL to open")
    browser_chat.add_argument("--file", default=None, help="prompt file; otherwise --task is used")
    browser_chat.add_argument("--task", default=None, help="BTASK-ID whose prompt should be sent")
    browser_chat.add_argument("--provider", default="chatgpt_web")
    browser_chat.add_argument("--profile", default=None)
    browser_chat.add_argument("--description", default=None, help="prepare a new task from this text, then send it")
    browser_chat.add_argument("--send", action="store_true", help="actually submit (default is a dry run)")
    browser_chat.add_argument("--pack", default=None, help="prompt pack file to send (project card + files + skills)")
    browser_chat.add_argument("--pack-files", default=None, help="comma separated files for a freshly built pack")
    browser_chat.add_argument("--timeout", type=int, default=600)
    browser_chat.add_argument("--shot", default=None)
    browser_chat.add_argument(
        "--new-conversation",
        action="store_true",
        help="open a brand new, verified-empty conversation before sending",
    )
    browser_chat.add_argument(
        "--keep-conversation",
        action="store_true",
        help="keep the new conversation in site history instead of archiving it after import",
    )
    browser_chat.add_argument(
        "--continue",
        dest="continue_url",
        default=None,
        help="continue an existing conversation URL instead of opening a new chat",
    )
    browser_chat.add_argument(
        "--force-import",
        action="store_true",
        help="replace an already validated result (refused by default)",
    )
    browser_chat.add_argument(
        "--allow-partial",
        action="store_true",
        help="import an answer that was still streaming when --timeout expired (refused by default)",
    )
    browser_chat.add_argument(
        "--artifacts-dir",
        default=None,
        help="where to write state.json/screenshot.png/timing.json (default: the task artifact dir)",
    )
    browser_read = browser_sub.add_parser("read", help="read the current page state and the last answer")
    browser_read.add_argument("--url", default=None, help="open this URL first (optional)")
    browser_read.add_argument("--save", default=None, help="write the last answer to this file")
    browser_read.add_argument("--json", action="store_true")
    visual = sub.add_parser("visual")
    visual_sub = visual.add_subparsers(dest="visual_cmd", required=True)
    visual_sub.add_parser("doctor")
    visual_run = visual_sub.add_parser("run")
    visual_run.add_argument("task_id")
    visual_run.add_argument("--url", required=True)
    visual_run.add_argument("--viewports", default=None, help="comma separated: desktop,mobile")
    harness = sub.add_parser("harness")
    harness_sub = harness.add_subparsers(dest="harness_cmd", required=True)
    harness_sub.add_parser("doctor")
    harness_codex = harness_sub.add_parser("codex", help="delegate a Harness task to Codex CLI")
    harness_codex.add_argument("task", nargs="?", default=None)
    harness_codex.add_argument("--file", default=None, help="read the delegated task from a file")
    harness_codex.add_argument("--output", default=None, help="where Codex writes its final answer")
    harness_codex.add_argument("--timeout", type=int, default=None)
    harness_codex.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write"],
        default="read-only",
        help="read-only for review/analysis, workspace-write when edits are explicitly intended",
    )
    harness_codex.add_argument("--json", action="store_true", help="print machine-readable result metadata")
    repo_map = sub.add_parser("map")
    repo_map_sub = repo_map.add_subparsers(dest="map_cmd", required=True)
    repo_map_build = repo_map_sub.add_parser("build")
    repo_map_build.add_argument("--force", action="store_true")
    repo_map_show = repo_map_sub.add_parser("show")
    repo_map_show.add_argument("--limit", type=int, default=40)
    repo_map_related = repo_map_sub.add_parser("related")
    repo_map_related.add_argument("path")
    repo_map_related.add_argument("--depth", type=int, default=2)
    run = sub.add_parser("run")
    run.add_argument("task")
    run.add_argument("--mode", choices=["fast", "safe"], default="safe")
    run.add_argument("--provider", choices=["codex", "groq", "openrouter", "mock"], default=None)
    run.add_argument("--dry-run", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("task_id")
    review = sub.add_parser("review")
    review.add_argument("task_id")
    report = sub.add_parser("report")
    report.add_argument("task_id")
    report.add_argument("--json", action="store_true", help="print the report as JSON")
    apply = sub.add_parser("apply")
    apply.add_argument("task_id")
    apply.add_argument("--yes", action="store_true", help="confirm applying the reviewed patch")
    args = parser.parse_args(argv)
    settings = load_settings(Path(args.project))
    controller = Controller(settings)
    try:
        if args.cmd == "doctor":
            return doctor(settings)
        if args.cmd == "init":
            write_example_config(Path(args.project) / "config" / "settings.yaml")
            print("Created config/settings.yaml")
            return 0
        if args.cmd == "providers":
            return providers(settings, as_json=getattr(args, "json", False))
        if args.cmd == "ui":
            return ui_command(args, settings, controller)
        if args.cmd == "context" and args.context_cmd == "preview":
            return context_preview(settings, controller)
        if args.cmd == "context" and args.context_cmd == "show":
            return context_show(settings, controller)
        if args.cmd == "context" and args.context_cmd == "pack":
            return context_pack_command(settings, controller, args)
        if args.cmd == "context" and args.context_cmd == "explain":
            return context_explain_command(settings, controller, args)
        if args.cmd == "skills":
            return skills_command(settings, controller, pack=args.pack)
        if args.cmd == "profile":
            return profile_command(settings, args.task)
        if args.cmd == "browser":
            return browser_command(args, settings, controller)
        if args.cmd == "visual":
            return visual_command(args, settings, controller)
        if args.cmd == "harness":
            return harness_command(args, settings)
        if args.cmd == "map":
            return map_command(args, settings)
        if args.cmd == "run":
            record = controller.run(args.task, args.mode, args.provider, args.dry_run)
            print_record(record)
            return 0 if record.status != "failed" else 2
        if args.cmd == "status":
            print_record(controller.status(args.task_id))
            return 0
        if args.cmd == "review":
            print(controller.diff(args.task_id) or "No diff available.")
            return 0
        if args.cmd == "report":
            from .report import ReportBuilder

            task_report = ReportBuilder(settings, controller).build(args.task_id)
            if args.json:
                print(json.dumps(task_report.to_dict(), indent=2, ensure_ascii=False))
            else:
                print(task_report.render_markdown(), end="")
                print(f"Saved: {task_report.json_path}")
                print(f"Saved: {task_report.markdown_path}")
            return 0
        if args.cmd == "apply":
            print_record(controller.apply(args.task_id, confirm=args.yes))
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


def _resolve_tool(name: str) -> str:
    """Resolve a configured tool the same way its provider does.

    `shutil.which` only searches PATH, so a trusted absolute command (which is
    exactly how Codex is configured here) reported "NOT FOUND" while the
    provider itself resolved it fine. Diagnostics must not contradict the
    provider they describe.
    """
    if not name:
        return "NOT FOUND"
    candidate = Path(name)
    if candidate.is_absolute():
        return str(candidate) if candidate.exists() else "NOT FOUND"
    if any(sep in name for sep in ("/", "\\")):
        return str(candidate) if candidate.exists() else "NOT FOUND"
    return shutil.which(name) or "NOT FOUND"


def doctor(settings) -> int:
    checks = {
        "Python": sys.version.split()[0],
        "Git": shutil.which("git") or "NOT FOUND",
        "Codex CLI": _resolve_tool(settings.raw["providers"]["codex"].get("command", "codex")),
        # PHP is not on PATH on the target machine; it lives under an OSPanel
        # modules tree. `php_binary()` already knows that layout and is what the
        # syntax checks use, so doctor must use it too or it under-reports.
        "PHP": php_binary() or "NOT FOUND",
        "Node": shutil.which("node") or "NOT FOUND",
    }
    for name, value in checks.items():
        print(f"{name}: {value}")
    print(f"Project: {settings.root}")
    print(f"State: {settings.state_file}")
    return 0


def providers(settings, as_json: bool = False) -> int:
    from .providers.status import (
        browser_provider_statuses,
        format_statuses,
        provider_statuses,
    )

    statuses = [*provider_statuses(settings), *browser_provider_statuses()]
    if as_json:
        print(json.dumps([status.as_dict() for status in statuses], indent=2, ensure_ascii=False))
        return 0
    print(format_statuses(statuses))
    print()
    print("Note: 'authenticated' means credentials were located, not that the model")
    print("answered. 'live_verified' requires a real successful call and is False")
    print("until one is performed.")
    for provider in [
        CodexProvider(settings.raw["providers"]["codex"]),
        GroqProvider(settings.raw["providers"]["groq"], settings.raw["budget"]),
        OpenRouterProvider(settings.raw["providers"]["openrouter"], settings.raw["budget"]),
    ]:
        cfg = settings.raw["providers"][provider.name]
        print(f"\n[{provider.name} settings]")
        for key, value in cfg.items():
            shown = "***" if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower() else value
            source = settings.sources.get(f"providers.{provider.name}.{key}", "project/default")
            print(f"  {key}: {shown} ({source})")
    return 0


def ui_command(args, settings, controller) -> int:
    from .browser_bridge import BrowserBridge
    from .local_ui import LocalUI

    bridge = BrowserBridge(settings, controller)
    ui = LocalUI(settings, bridge, controller, host=args.host, port=args.port)
    if not args.no_browser:
        try:
            webbrowser.open(ui.url())
        except Exception:
            pass
    ui.start(block=True)
    return 0


def context_preview(settings, controller) -> int:
    files = controller._target_files(settings.root, cloud=True)
    print("Cloud context preview:")
    if not files:
        print("No files selected for cloud context.")
        print("Set context.allowed_files in config/settings.yaml for explicit non-sensitive files.")
        return 0
    for path in files:
        rel = path.relative_to(settings.root).as_posix()
        print(f"- {rel} ({path.stat().st_size} bytes)")
    return 0


def repo_map_for(settings, refresh: bool = False):
    """The repository map, cached on disk and rebuilt only when a file changed.

    Returns None when the project has no allowed files to map, so callers can
    tell "no map" apart from "an empty map".
    """
    from .context.repo_map import RepoMapBuilder

    if not settings.raw.get("context", {}).get("allowed_files"):
        return None
    builder = RepoMapBuilder(settings)
    if not refresh:
        cached = builder.load_cached()
        if cached is not None:
            return cached
    repo_map = builder.build()
    builder.save(repo_map)
    return repo_map


def _context_builder(settings, repo_map=None):
    from .context import ContextBuilder

    if repo_map is None:
        repo_map = repo_map_for(settings)
    return ContextBuilder(settings, repo_map=repo_map)


def context_explain_command(settings, controller, args) -> int:
    """Show the file selection for one task, with a reason per file."""
    from .context import PROFILES

    repo_map = None if args.no_repo_map else repo_map_for(settings)
    builder = _context_builder(settings, repo_map=repo_map)
    selection = builder.explain(args.task, args.profile)
    if args.json:
        print(
            json.dumps(
                {
                    "profile": selection.profile,
                    "repo_map_used": selection.repo_map_used,
                    "tokens": selection.tokens,
                    "selected": [
                        {"path": choice.path, "score": round(choice.score, 2), "reason": choice.reason}
                        for choice in selection.choices
                    ],
                    "excluded": [{"path": path, "reason": why} for path, why in selection.excluded],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(selection.render())
    if not selection.choices:
        print("")
        print("Nothing would be attached. Set context.allowed_files in the trusted user config;")
        print(f"a project may only narrow that list, never widen it. Known profiles: {', '.join(sorted(PROFILES))}.")
    return 0


def context_show(settings, controller) -> int:
    """Show the pack the trusted configuration allows for each profile."""
    from .context import PROFILE_TRIGGERS, PROFILES

    builder = _context_builder(settings)
    print(f"Skills directory: {builder.skills_dir}")
    print(f"Design directory: {builder.design_dir}")
    print(f"Profiles directory: {builder.profiles_dir}")
    print(f"Max context chars: {builder.max_chars}")
    allowed = settings.raw.get("context", {}).get("allowed_files", [])
    print(f"Allowed files ({len(allowed)}):")
    for rel in allowed:
        print(f"- {rel}")
    print("\nProfiles:")
    for name in sorted(PROFILES):
        print(f"- {name}: {', '.join(PROFILES[name])}")
    print("\nRouting keywords:")
    for name, triggers in sorted(PROFILE_TRIGGERS.items()):
        print(f"- {name}: {', '.join(triggers[:6])}")
    return 0


def context_pack_command(settings, controller, args) -> int:
    """Assemble a complete prompt pack: project card + files + skills + contract."""
    from .context.prompt_pack import ContextPackWriter
    from .tasks import TaskRecord

    files = [item.strip() for item in (args.files or "").split(",") if item.strip()]
    record = TaskRecord.new(args.task, "browser", "chatgpt_web", "medium", settings.root)
    writer = ContextPackWriter(settings)
    pack = writer.build(record, args.profile, files or None)

    out = Path(args.out) if args.out else Path(settings.data_dir) / "prompt-pack.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(pack.text, encoding="utf-8", newline="\n")

    print(f"profile: {pack.profile}")
    print(f"skills: {', '.join(pack.skills) or 'none'}")
    print(f"files ({len(pack.files)}):")
    for path, size in pack.files:
        print(f"- {path} ({size} chars)")
    if pack.truncated:
        print(f"truncated: {', '.join(pack.truncated)}")
    if pack.missing:
        print(f"missing: {', '.join(pack.missing)}")
    print(f"pack: {out} ({len(pack.text)} chars)")
    print("")
    print("Preview (first 25 lines):")
    for line in pack.text.splitlines()[:25]:
        print(f"  {line}")
    return 0


def skills_command(settings, controller, pack: bool = False) -> int:
    from .tasks import TaskRecord

    builder = _context_builder(settings)
    catalog = builder.skills()
    print(f"Skills found: {len(catalog)}")
    for name, skill in sorted(catalog.items()):
        description = skill.description or "(no description)"
        print(f"- {name}: {description}")
        if skill.triggers:
            print(f"    triggers: {', '.join(skill.triggers[:8])}")
    if not catalog:
        print(f"No SKILL.md files found under {builder.skills_dir}")

    if pack:
        probe = TaskRecord.new("demo context pack for the current project", "browser", "browser", "medium", settings.root)
        built = builder.build(probe)
        print("\n=== Context Pack preview ===")
        print(f"profile: {built.profile}")
        print(f"skills: {', '.join(built.skill_names()) or 'none'}")
        print(f"sections: {', '.join(sorted(built.sections)) or 'none'}")
        print(f"files: {', '.join(built.used_files()) or 'none'}")
        if built.missing:
            print(f"missing: {', '.join(built.missing)}")
        if built.truncated:
            print(f"truncated: {', '.join(built.truncated)}")
    return 0


def profile_command(settings, description) -> int:
    from .context import PROFILES, choose_profile

    if not description:
        builder = _context_builder(settings)
        print("Profiles:")
        for name, skills in sorted(builder.profiles().items()):
            print(f"- {name}: {', '.join(skills) or '(skills not listed)'}")
        missing = [name for name in PROFILES if name not in builder.profiles()]
        if missing:
            print(f"Known profiles without a yaml file: {', '.join(missing)}")
        return 0
    try:
        chosen = choose_profile(description, None)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Description: {description}")
    print(f"Profile: {chosen}")
    print(f"Skills: {', '.join(PROFILES.get(chosen, []))}")
    return 0


def browser_command(args, settings, controller) -> int:
    from .browser_bridge import BrowserBridge, BrowserBridgeError, ResponseAlreadyImported

    bridge = BrowserBridge(settings, controller)

    if args.browser_cmd == "providers":
        print("Browser AI Bridge providers (relay mode: you sign in and paste answers yourself)")
        for entry in bridge.provider_status():
            state = "AVAILABLE" if entry["available"] else "UNAVAILABLE"
            print(f"- {entry['name']} ({entry['display_name']}): {state}")
            print(f"    url: {entry['url']}")
            print(f"    mode: {entry['mode']}")
            print(f"    detail: {entry['detail']}")
        print("\nNo cookies, tokens or browser profile data are read or stored.")
        return 0

    if args.browser_cmd == "history":
        tasks = bridge.history()
        if not tasks:
            print("No browser tasks yet.")
            return 0
        for task in tasks:
            print(f"{task.task_id}  {task.provider:<14} {task.profile:<15} {task.status:<18} {task.description[:60]}")
        return 0

    if args.browser_cmd == "prepare":
        task = bridge.prepare(args.task, args.provider, args.profile)
        print(f"Browser task: {task.task_id}")
        print(f"Engine task: {task.engine_task_id}")
        print(f"Provider: {task.provider}")
        print(f"Profile: {task.profile}")
        print(f"Skills: {', '.join(task.skills)}")
        print(f"Prompt: {task.prompt_path}")
        print(f"Status: {task.status}")
        print("Nothing was sent anywhere. Next steps:")
        print(f"  1. hybrid browser launch            # once: sign in in the opened window")
        print(f"  2. hybrid browser say --task {task.task_id} --send")
        print(f"  3. hybrid browser import {task.task_id} --file answer.md")
        return 0

    if args.browser_cmd in {"launch", "status", "at", "say", "chat", "read"}:
        return live_browser_command(args, settings, bridge)

    if args.browser_cmd == "prompt":
        print(bridge.prompt(args.task_id))
        return 0

    if args.browser_cmd == "open":
        url = bridge.open(args.task_id)
        print(f"Opened {url} in your default browser. Sign in yourself; the engine stores no credentials.")
        return 0

    if args.browser_cmd == "diff":
        text = bridge.diff(args.task_id)
        print(text or "No diff available.")
        return 0

    if args.browser_cmd == "review":
        payload = bridge.review_payload(args.task_id)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.browser_cmd == "cancel":
        task = bridge.cancel(args.task_id)
        print(f"{task.task_id}: {task.status}")
        return 0

    if args.browser_cmd == "request-review":
        task = bridge.prepare_review(args.task_id, args.reviewer)
        print(f"Review task: {task.task_id}")
        print(f"Provider: {task.provider}")
        print(f"Prompt: {task.prompt_path}")
        print(f"Next: hybrid browser open {task.task_id}")
        return 0

    if args.browser_cmd == "import":
        text = _read_imported_text(args)
        if text is None:
            return 1
        record = bridge.import_response(args.task_id, text, force=args.force)
        print_record(record)
        if record.status == "ready_for_review":
            print("Review the diff with `hybrid review %s`, then apply with `hybrid apply %s --yes`." % (record.task_id, record.task_id))
            return 0
        if record.status == "failed":
            return 2
        return 0

    raise BrowserBridgeError(f"Unknown browser command: {args.browser_cmd}")


def _archive_artifact(path: Path, keep: int = 3) -> Path | None:
    """Move an existing artifact aside instead of silently overwriting it.

    Used for the answer record, so a forced re-import still leaves a trace of
    what was replaced. The history is bounded to ``keep`` entries per artifact.
    """
    path = Path(path)
    if not path.exists():
        return None
    history = path.parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = history / f"{path.stem}-{stamp}{path.suffix}"
    counter = 2
    while target.exists():
        target = history / f"{path.stem}-{stamp}-{counter}{path.suffix}"
        counter += 1
    path.replace(target)
    for stale in sorted(history.glob(f"{path.stem}-*{path.suffix}"))[:-keep]:
        stale.unlink(missing_ok=True)
    return target


def _resolve_artifacts_dir(args, settings, default: Path | None) -> Path | None:
    """Resolve `--artifacts-dir`, refusing paths that could be committed.

    Diagnostics contain a screenshot and a DOM skeleton, so writing them into
    the project tree outside the ignored `.hybrid/` directory would put page
    content one `git add` away from the repository. Paths outside the project
    entirely are the user's own business (a temp dir, a scratch volume).

    ``default=None`` validates the explicit flag only, for callers that want to
    fail before creating anything.
    """
    if not args.artifacts_dir:
        return default
    target = Path(args.artifacts_dir).expanduser().resolve()
    root = Path(settings.root).resolve()
    data_dir = Path(settings.data_dir).resolve()
    try:
        inside_project = target == root or target.is_relative_to(root)
        inside_state = target == data_dir or target.is_relative_to(data_dir)
    except AttributeError:  # pragma: no cover - Python < 3.9
        inside_project = str(target).startswith(str(root))
        inside_state = str(target).startswith(str(data_dir))
    if inside_project and not inside_state:
        print(
            f"ERROR: --artifacts-dir {target} is inside the project but outside {data_dir}.",
            file=sys.stderr,
        )
        print(
            "Browser artifacts include a screenshot and a DOM skeleton; they must stay in the "
            "ignored state directory, or outside the project entirely.",
            file=sys.stderr,
        )
        return None
    return target


def chat_automation_command(args, settings, bridge, session) -> int:
    """One command: prompt -> verify insert -> submit -> wait for the new answer -> import.

    The import is never forced implicitly: replacing a result that already went
    through validation requires the explicit `--force-import` flag. A partial
    answer (the stream was still moving at the deadline) is refused unless
    `--allow-partial` is passed, so a truncated response cannot masquerade as a
    finished one.
    """
    from .browser_bridge.cdp import CdpError
    from .browser_bridge.sessions import BrowserBridgeError, ResponseAlreadyImported
    from .browser_bridge.sites import site_for_provider, site_for_url
    from .browser_bridge.webchat import WebChatAutomation

    try:
        profile = site_for_provider(args.provider)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    target_url = args.continue_url or args.url or profile.new_conversation_url
    if args.url and not args.continue_url:
        url_profile = site_for_url(args.url)
        if url_profile is not None:
            profile = url_profile
    if args.new_conversation and any(
        not profile.selectors.get(name) for name in ("composer", "send_button", "assistant_message", "answer_body")
    ):
        print(
            f"ERROR: {profile.display_name} has no live-verified browser selectors yet; "
            "refusing to open or type into an unverified page.",
            file=sys.stderr,
        )
        return 5
    if args.keep_conversation and not profile.supports_archive:
        print(f"NOTE: {profile.display_name} does not support verified archiving; --keep-conversation has no effect.")

    if args.new_conversation and args.continue_url:
        print("ERROR: --new-conversation and --continue are mutually exclusive", file=sys.stderr)
        return 1
    if args.new_conversation:
        try:
            _chat_root_url(target_url, profile)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if args.continue_url:
        parsed_continue = urlparse(args.continue_url)
        if (
            parsed_continue.scheme != "https"
            or parsed_continue.hostname not in profile.hostnames
            or not profile.conversation_url_re.fullmatch(parsed_continue.path or "")
        ):
            print(f"ERROR: --continue requires a verified {profile.display_name} conversation URL", file=sys.stderr)
            return 1
    if args.description and args.task:
        print(
            "ERROR: --description prepares a NEW task, so combining it with --task is ambiguous. "
            "Pass one of them.",
            file=sys.stderr,
        )
        return 1
    # Validate an explicit artifacts path before any task is created, so a
    # refused run leaves no half-prepared task behind.
    if args.artifacts_dir and _resolve_artifacts_dir(args, settings, None) is None:
        return 1

    browser_task_id = args.task
    if args.description:
        task = bridge.prepare(args.description, args.provider, args.profile)
        browser_task_id = task.task_id
        print(f"prepared: {task.task_id} (engine {task.engine_task_id})")
    elif args.file and not browser_task_id:
        # A prompt file without a task still needs a task to import the answer
        # into, so create one from the file's own first line.
        preview = Path(args.file).read_text(encoding="utf-8").strip().splitlines()
        description = preview[0][:200] if preview else "prompt from file"
        task = bridge.prepare(description, args.provider, args.profile)
        browser_task_id = task.task_id
        print(f"prepared from file: {task.task_id} (engine {task.engine_task_id})")
        print(f"  note: the task description came from the first line of {args.file}: {description!r}")
        print("  pass --task BTASK-ID to send into an existing task instead.")
    if not browser_task_id:
        print("ERROR: pass --task BTASK-ID, --description \"...\" or --file <prompt.md>", file=sys.stderr)
        return 1

    prompt_source = "task"
    if args.file:
        prompt_source = f"file:{args.file}"
        prompt_text = Path(args.file).read_text(encoding="utf-8")
    elif args.pack:
        prompt_source = f"pack:{args.pack}"
        prompt_text = Path(args.pack).read_text(encoding="utf-8")
    elif args.pack_files:
        from .context.prompt_pack import ContextPackWriter

        prompt_source = f"pack-files:{args.pack_files}"
        writer = ContextPackWriter(settings)
        files = [item.strip() for item in args.pack_files.split(",") if item.strip()]
        built = writer.build(
            bridge.controller.store.get(bridge.task(browser_task_id).engine_task_id),
            args.profile,
            files,
        )
        prompt_text = built.text
        pack_path = Path(settings.data_dir) / "prompt-pack.md"
        pack_path.write_text(prompt_text, encoding="utf-8", newline="\n")
        print(f"pack built: {pack_path} ({len(prompt_text)} chars, files: {len(built.files)})")
    else:
        prompt_text = bridge.prompt(browser_task_id)

    # Immutable record of exactly what was sent with this task id. It is written
    # to the artifacts directory before the browser run; the task metadata only
    # learns the hash once an import is actually accepted.
    prompt_sha256 = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    browser_task = bridge.task(browser_task_id)
    artifacts_dir = _resolve_artifacts_dir(
        args,
        settings,
        bridge.controller._artifact_dir(browser_task.engine_task_id or browser_task_id) / "browser",
    )
    if artifacts_dir is None:
        return 1
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _archive_artifact(artifacts_dir / "prompt.json")
    prompt_artifact = {
        "browser_task_id": browser_task_id,
        "engine_task_id": browser_task.engine_task_id,
        "provider": browser_task.provider,
        "profile": browser_task.profile,
        "prompt_source": prompt_source,
        "prompt_sha256": prompt_sha256,
        "prompt_length": len(prompt_text),
        "created_at": time.time(),
    }
    (artifacts_dir / "prompt.json").write_text(
        json.dumps(prompt_artifact, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"prompt: {len(prompt_text)} chars sha256={prompt_sha256[:12]} source={prompt_source}")

    created_conversation = bool(args.new_conversation or (not args.continue_url and _is_chat_root_url(target_url, profile)))
    page = session.open_page(target_url)
    automation = WebChatAutomation(page, artifacts_dir=artifacts_dir, stable_seconds=2.0, profile=profile)
    try:
        if created_conversation:
            new_chat_url = _chat_root_url(target_url, profile) if args.new_conversation else target_url
            if profile.new_conversation is None:
                raise CdpError(f"{profile.display_name} new-conversation behavior has not been verified")
            state = profile.new_conversation(page, new_chat_url)
            print(f"new conversation: {state.url} (assistants={state.assistant_count})")
        elif args.continue_url:
            print(f"continuing conversation: {args.continue_url}")

        effort = automation.effort_label()
        print(f"reasoning effort: {effort or 'unknown'}")
        if not args.send:
            automation.ask(prompt_text, submit=False)
            if args.shot:
                page.screenshot(Path(args.shot))
            print("Dry run: text is in the box, nothing was submitted. Add --send to submit.")
            return 0

        print("submitting ...")
        answer = automation.ask(prompt_text, timeout_seconds=args.timeout, submit=True)
        print(f"conversation: {answer.conversation_url}")
        print(f"answer: {len(answer.text)} chars in {answer.seconds:.1f}s key={answer.key or '?'}")
        if args.shot:
            page.screenshot(Path(args.shot))
            print(f"screenshot: {args.shot}")
        if not answer.answered:
            print("ERROR: the web chat produced no answer", file=sys.stderr)
            return 3
        if not answer.complete and not args.allow_partial:
            print(
                "ERROR: could not prove the answer finished"
                + (
                    f" (the stream was still moving when the {args.timeout}s timeout expired)"
                    if answer.stage == "STREAM_FINISHED"
                    else ""
                )
                + f", so the captured text ({len(answer.text)} chars) may be truncated.",
                file=sys.stderr,
            )
            print("Nothing was imported. Re-run with a larger --timeout, or pass", file=sys.stderr)
            print("--allow-partial if a truncated answer is genuinely what you want.", file=sys.stderr)
            return 6

        answer_sha256 = hashlib.sha256(answer.text.encode("utf-8")).hexdigest()
        _archive_artifact(artifacts_dir / "answer.json")
        (artifacts_dir / "answer.json").write_text(
            json.dumps(
                {
                    "prompt_sha256": prompt_sha256,
                    "prompt_source": prompt_source,
                    "answer_sha256": answer_sha256,
                    "answer_chars": len(answer.text),
                    "answer_key": answer.key,
                    "answer_complete": answer.complete,
                    "conversation_url": answer.conversation_url,
                    "stage": answer.stage,
                    "baseline": answer.baseline.to_dict() if answer.baseline else {},
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        (artifacts_dir / "timing.json").write_text(
            json.dumps(automation.trace.to_dict(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print("timings:")
        print(automation.trace.render())

        record = bridge.import_response(
            browser_task_id,
            answer.text,
            force=args.force_import,
            conversation_url=answer.conversation_url,
            prompt_sha256=prompt_sha256,
            prompt_source=prompt_source,
            partial=not answer.complete,
        )
        print(f"imported into {record.task_id}: status={record.status}")
        for name, result in record.checks.items():
            print(f"  - {name}: {result['status']}")
        if created_conversation and not args.keep_conversation and profile.supports_archive and profile.archive_conversation:
            try:
                archived = profile.archive_conversation(page, answer.conversation_url)
            except CdpError as exc:
                archived = False
                print(f"WARNING: answer imported, but its {profile.display_name} conversation could not be archived: {exc}", file=sys.stderr)
            if archived:
                print(f"conversation archived from {profile.display_name} history (answer and provenance remain in the task)")
            else:
                print(
                    f"WARNING: answer imported, but the {profile.display_name} conversation is still in history; "
                    "archive it manually if desired.",
                    file=sys.stderr,
                )
        elif created_conversation and profile.supports_archive:
            print(f"conversation kept in {profile.display_name} history (--keep-conversation)")
        if record.status == "ready_for_review":
            print(f"review the diff: hybrid browser diff {browser_task_id}")
            print(f"apply:           hybrid apply {record.task_id} --yes")
        return 0
    except CdpError as exc:
        print(f"ERROR: browser automation failed at stage {automation.stage}: {exc}", file=sys.stderr)
        if automation.last_diagnostics:
            print(f"artifacts: {automation.last_diagnostics.parent}", file=sys.stderr)
        return 5
    except ResponseAlreadyImported as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print(
            f"hint: the answer was already imported; add --force-import to replace the validated result "
            f"for {browser_task_id}",
            file=sys.stderr,
        )
        return 4
    except BrowserBridgeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        page.close()


def _is_chat_root_url(url: str, profile=None) -> bool:
    if profile is None:
        from .browser_bridge.sites import default_site

        profile = default_site()
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in profile.hostnames and parsed.path in {"", "/"}


def _chat_root_url(url: str, profile=None) -> str:
    if profile is None:
        from .browser_bridge.sites import default_site

        profile = default_site()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in profile.hostnames:
        raise ValueError(f"--new-conversation requires an https URL for {profile.display_name}")
    return urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))


def live_browser_command(args, settings, bridge) -> int:
    """Drive the shared, user-authenticated Chrome session over CDP."""
    from .browser_bridge.cdp import CdpError
    from .browser_bridge.session_live import BrowserSession

    session = BrowserSession(settings)

    if args.browser_cmd == "launch":
        state = session.launch(args.url)
        print(f"Chrome session: http://127.0.0.1:{state.port}")
        print(f"Profile: {state.profile_dir}")
        print(f"Version: {state.version}")
        print("Sign in to the sites you need in this window (ChatGPT, DeepSeek, ...).")
        print("The engine stores no passwords; the profile is a normal Chrome profile.")
        print("When you are signed in, run: hybrid browser status")
        return 0

    if args.browser_cmd == "status":
        state = session.state()
        if not state.running:
            print(f"Session: NOT RUNNING (port {state.port})")
            print("Start it with: hybrid browser launch")
            return 1
        ours = session.is_ours()
        print(f"Session: RUNNING on port {state.port}")
        print(f"Profile: {state.profile_dir}")
        print(f"Browser: {state.version}")
        print(f"Drivable by the engine: {'yes' if ours else 'no'}")
        if not ours:
            print("Another browser probably owns this port; relaunch with `hybrid browser launch`.")
        return 0

    if args.browser_cmd == "at":
        from .browser_bridge.sites import default_site

        page = session.open_page(args.url or default_site().new_conversation_url)
        try:
            title = page.eval("document.title")
            print(f"URL: {page.eval('location.href')}")
            print(f"Title: {title}")
            if args.check:
                print(f"Check: {page.eval(args.check)}")
            if args.shot:
                saved = page.screenshot(Path(args.shot))
                print(f"Screenshot: {'saved' if saved else 'failed'} -> {args.shot}")
        finally:
            page.close()
        return 0

    if args.browser_cmd == "read":
        from .browser_bridge.cdp import CdpError
        from .browser_bridge.sites import default_site, site_for_url
        from .browser_bridge.webchat import WebChatAutomation

        read_url = args.url or session.start_url
        profile = site_for_url(read_url) or default_site()
        page = session.open_page(read_url)
        try:
            automation = WebChatAutomation(page, profile=profile)
            # Let the SPA mount before diagnosing it: navigating and probing
            # immediately reports an un-hydrated shell with no messages.
            automation.reader.wait_ready(timeout=30.0)
            payload = {
                **automation.state(),
                **automation.diagnose(),
                "effort": automation.effort_label(),
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"URL: {payload['url']}")
                print(f"Title: {payload['title']}")
                print(f"Mode: {payload['mode']}  Reasoning effort: {payload['effort'] or 'unknown'}")
                print(f"Messages: {payload['assistant_count']} answers, last {payload['last_answer_chars']} chars")
                print(f"Streaming: {payload['stop_button']}  Composer: {payload['composer_chars']} chars")
                print("Selectors:")
                for line in payload["selector_report"]:
                    print(f"  {line}")
                for blocker in payload["blockers"]:
                    print(f"  BLOCKER: {blocker}")
            if args.save:
                if not payload.get("last_answer_key"):
                    answer = ""
                else:
                    answer = automation.reader.answer_text(key=payload["last_answer_key"])
                if payload.get("last_answer_key") and not answer.strip():
                    print("ERROR: an assistant message was identified, but its answer body could not be extracted", file=sys.stderr)
                    return 5
                target = Path(args.save)
                target.write_text(answer, encoding="utf-8", newline="\n")
                print(f"answer saved: {target} ({len(answer)} chars)")
            return 0
        except CdpError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 5
        finally:
            page.close()

    if args.browser_cmd == "chat":
        return chat_automation_command(args, settings, bridge, session)

    if args.browser_cmd == "say":
        from .browser_bridge.webchat import AnswerBaseline, WebChatAutomation

        text = args.text
        if args.file:
            path = Path(args.file)
            if not path.is_file():
                print(f"ERROR: file not found: {path}", file=sys.stderr)
                return 1
            text = path.read_text(encoding="utf-8")
        if args.task:
            text = bridge.prompt(args.task)
        if not text:
            print("ERROR: pass message text, --file or --task BTASK-ID", file=sys.stderr)
            return 1
        from .browser_bridge.sites import default_site, site_for_url

        page = session.open_page(args.url or default_site().new_conversation_url)
        try:
            automation = WebChatAutomation(page, profile=site_for_url(args.url or "") or default_site())
            state = automation.ensure_ready()
            print(f"Page: {state.render()}")
            typed = automation.insert_prompt(text)
            print(f"Inserted: {typed.composer_chars} chars, head={typed.composer_tail!r}")
            if args.shot:
                page.screenshot(Path(args.shot))
                print(f"Screenshot: {args.shot}")
            if not args.send:
                print("Dry run: nothing was submitted. Add --send to submit.")
                return 0
            baseline = AnswerBaseline.of(typed)
            automation.submit_prompt(baseline)
            print("Submitted: True")
            return 0
        except CdpError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 5
        finally:
            page.close()


def visual_command(args, settings, controller) -> int:
    from .visual import VIEWPORTS, VisualQA

    qa = VisualQA(settings, controller=controller)

    if args.visual_cmd == "doctor":
        ok, detail = qa.available()
        print(f"Browser driver: {'AVAILABLE' if ok else 'UNAVAILABLE'}")
        print(f"Detail: {detail}")
        print("Viewports: " + ", ".join(f"{name} {size[0]}x{size[1]}" for name, size in VIEWPORTS.items()))
        return 0 if ok else 1

    if args.visual_cmd == "run":
        try:
            controller.store.get(args.task_id)
        except KeyError:
            print(f"ERROR: Unknown task: {args.task_id}", file=sys.stderr)
            return 1
        selected = None
        if args.viewports:
            names = [name.strip() for name in args.viewports.split(",") if name.strip()]
            unknown = [name for name in names if name not in VIEWPORTS]
            if unknown:
                print(f"ERROR: Unknown viewports: {', '.join(unknown)}. Known: {', '.join(VIEWPORTS)}", file=sys.stderr)
                return 1
            selected = {name: VIEWPORTS[name] for name in names}
        report = qa.run(args.task_id, args.url, selected)
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        print(f"Saved: {report.report_path}")
        print(f"Saved: {report.markdown_path}")
        return 0 if report.status in {"pass", "not_run"} else 2

    print(f"ERROR: Unknown visual command: {args.visual_cmd}", file=sys.stderr)
    return 1


def harness_command(args, settings) -> int:
    adapter = DeepSeekHarnessAdapter(settings.raw["deepseek_harness"])
    if args.harness_cmd == "doctor":
        ok, detail = adapter.available()
        config = settings.raw["deepseek_harness"]
        print(f"DeepSeek Harness SDK: {'AVAILABLE' if ok else 'UNAVAILABLE'}")
        print(f"Detail: {detail}")
        print(f"Enabled: {config.get('enabled', False)}")
        print(f"Max parallel agents: {config.get('max_parallel_agents')}")
        print(f"Timeout seconds: {config.get('timeout_seconds')}")
        return 0 if ok else 1
    if args.harness_cmd == "codex":
        if args.file and args.task:
            print("ERROR: pass either --file or an inline task, not both", file=sys.stderr)
            return 1
        if args.file:
            task_path = Path(args.file)
            if not task_path.is_file():
                print(f"ERROR: task file not found: {task_path}", file=sys.stderr)
                return 1
            description = task_path.read_text(encoding="utf-8")
        else:
            description = args.task
        if not description or not description.strip():
            print("ERROR: pass a task string or --file <task.md>", file=sys.stderr)
            return 1
        delegate = CodexCliDelegate(settings.raw["providers"]["codex"])
        output_path = Path(args.output) if args.output else None
        result = delegate.run_task(
            description,
            settings.root,
            timeout=args.timeout,
            sandbox=args.sandbox,
            output_path=output_path,
        )
        if args.json:
            print(result_json(result), end="")
        else:
            print(f"Codex delegation: {result.status}")
            print(f"Sandbox: {args.sandbox}")
            if result.output_path:
                print(f"Output: {result.output_path}")
            if result.error:
                print(f"Error: {result.error}", file=sys.stderr)
        return 0 if result.status == "ok" else 2
    print(f"ERROR: Unknown harness command: {args.harness_cmd}", file=sys.stderr)
    return 1


def map_command(args, settings) -> int:
    from .context.repo_map import RepoMapBuilder

    builder = RepoMapBuilder(settings)
    if args.map_cmd == "build":
        repo_map = None if args.force else builder.load_cached()
        if repo_map is None:
            repo_map = builder.build()
            path = builder.save(repo_map)
            print(f"Built repo map: {path}")
        else:
            print(f"Using cached repo map: {builder.cache_path()}")
        print(repo_map.summary())
        return 0
    if args.map_cmd == "show":
        repo_map = builder.load_cached()
        if repo_map is None:
            repo_map = builder.build()
            builder.save(repo_map)
        print(repo_map.summary(limit=args.limit))
        return 0
    if args.map_cmd == "related":
        repo_map = builder.load_cached()
        if repo_map is None:
            repo_map = builder.build()
            builder.save(repo_map)
        for rel in repo_map.related(args.path, depth=args.depth):
            print(rel)
        return 0
    print(f"ERROR: Unknown map command: {args.map_cmd}", file=sys.stderr)
    return 1


def _read_imported_text(args) -> str | None:
    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"ERROR: answer file not found: {path}", file=sys.stderr)
            return None
        return path.read_text(encoding="utf-8")
    if args.text:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    print(
        "ERROR: paste the answer with --file <path>, --text \"...\", or pipe it into the command.",
        file=sys.stderr,
    )
    return None


def print_record(record) -> None:
    print(f"{record.task_id}")
    print(f"Status: {record.status}")
    print(f"Mode: {record.mode}")
    print(f"Provider: {record.provider}")
    print(f"Complexity: {record.complexity}")
    if record.worktree_dir:
        print(f"Worktree: {record.worktree_dir}")
    if record.changed_files:
        print("Changed Files:")
        for item in record.changed_files:
            print(f"- {item}")
    if record.checks:
        print("Checks:")
        for name, result in record.checks.items():
            if isinstance(result, dict):
                print(f"- {name}: {result.get('status')}")
            else:
                print(f"- {name}: {result}")
    if record.error:
        print(f"Error: {record.error}")


if __name__ == "__main__":
    raise SystemExit(main())

