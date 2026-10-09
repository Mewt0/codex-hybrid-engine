from __future__ import annotations

from html import escape
from json import dumps
from typing import Any


PROFILES = ["frontend", "backend-php", "database", "fullstack-game"]


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: system-ui, sans-serif; color: #151515; background: #f7f7f4; }}
    header, main {{ max-width: 1040px; margin: 0 auto; padding: 20px; }}
    header {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; }}
    a {{ color: #075985; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #ddd; text-align: left; vertical-align: top; }}
    input, textarea, select {{ width: 100%; box-sizing: border-box; padding: 8px; font: inherit; }}
    textarea {{ min-height: 180px; font-family: ui-monospace, monospace; }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .panel {{ background: white; border: 1px solid #ddd; padding: 16px; margin: 14px 0; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }}
    button, .button {{ border: 1px solid #222; background: #222; color: white; padding: 8px 12px; text-decoration: none; cursor: pointer; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #1f2937; color: #f9fafb; padding: 12px; }}
    .muted {{ color: #555; }}
    @media (max-width: 720px) {{ .row {{ grid-template-columns: 1fr; }} header {{ align-items: flex-start; flex-direction: column; }} }}
  </style>
</head>
<body>
<header>
  <h1>{escape(title)}</h1>
  <nav><a href="/">Tasks</a> <a href="/new">New task</a></nav>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def dashboard(tasks: list[Any]) -> str:
    rows = []
    for task in tasks:
        rows.append(
            "<tr>"
            f"<td><a href=\"/task/{escape(task.task_id)}\">{escape(task.task_id)}</a></td>"
            f"<td>{escape(task.status)}</td>"
            f"<td>{escape(task.provider)}</td>"
            f"<td>{escape(task.profile)}</td>"
            f"<td>{escape(task.description)}</td>"
            "</tr>"
        )
    body = "<p><a class=\"button\" href=\"/new\">Prepare task</a></p>"
    if rows:
        body += "<table><thead><tr><th>Task</th><th>Status</th><th>Provider</th><th>Profile</th><th>Description</th></tr></thead><tbody>"
        body += "".join(rows) + "</tbody></table>"
    else:
        body += "<p class=\"muted\">No browser tasks yet.</p>"
    return page("Local Web Workspace", body)


def new_task(csrf: str, providers: list[str]) -> str:
    provider_options = "".join(f"<option value=\"{escape(item)}\">{escape(item)}</option>" for item in providers)
    profile_options = "".join(f"<option value=\"{escape(item)}\">{escape(item)}</option>" for item in PROFILES)
    body = f"""<form method="post" action="/prepare" class="panel">
  <input type="hidden" name="csrf" value="{escape(csrf)}">
  <p><label>Description<br><textarea name="description" required></textarea></label></p>
  <div class="row">
    <p><label>Provider<br><select name="provider">{provider_options}</select></label></p>
    <p><label>Profile<br><select name="profile">{profile_options}</select></label></p>
  </div>
  <p><button type="submit">Prepare</button></p>
</form>"""
    return page("New Task", body)


def task_detail(task: Any, record: Any, prompt: str, csrf: str) -> str:
    checks = dumps(record.checks, indent=2, ensure_ascii=False) if getattr(record, "checks", None) else "{}"
    warnings = escape(getattr(record, "error", "") or "")
    skills = ", ".join(getattr(record, "skills", []) or getattr(task, "skills", []) or [])
    files = ", ".join(getattr(record, "changed_files", []) or [])
    body = f"""<section class="panel">
  <p><strong>Status:</strong> {escape(getattr(record, "status", task.status))}</p>
  <p><strong>Provider:</strong> {escape(task.provider)} <strong>Profile:</strong> {escape(task.profile)}</p>
  <p><strong>Engine task:</strong> {escape(getattr(task, "engine_task_id", "") or "")}</p>
  <p><strong>Skills:</strong> {escape(skills)}</p>
  <p><strong>Changed files:</strong> {escape(files)}</p>
  <p><strong>Warnings:</strong> {warnings}</p>
  <div class="actions">
    <a class="button" href="/open/{escape(task.task_id)}">Open chat</a>
    <a class="button" href="/diff/{escape(task.task_id)}">Diff</a>
    <a class="button" href="/review/{escape(task.task_id)}">Review JSON</a>
  </div>
</section>
<section class="panel">
  <h2>Prompt</h2>
  <pre>{escape(prompt)}</pre>
</section>
<section class="panel">
  <h2>Import response</h2>
  <form method="post" action="/import">
    <input type="hidden" name="csrf" value="{escape(csrf)}">
    <input type="hidden" name="task_id" value="{escape(task.task_id)}">
    <p><textarea name="text" required></textarea></p>
    <p><label><input style="width:auto" type="checkbox" name="force" value="1"> Force replace</label></p>
    <p><button type="submit">Import</button></p>
  </form>
</section>
<section class="panel">
  <h2>Apply</h2>
  <form method="post" action="/apply">
    <input type="hidden" name="csrf" value="{escape(csrf)}">
    <input type="hidden" name="task_id" value="{escape(task.task_id)}">
    <p><label>Confirm<br><input name="confirm" autocomplete="off"></label></p>
    <p><button type="submit">Apply</button></p>
  </form>
</section>
<section class="panel">
  <h2>Checks</h2>
  <pre>{escape(checks)}</pre>
</section>"""
    return page(task.task_id, body)


def opened(task_id: str, url: str) -> str:
    body = f"""<section class="panel">
  <p>Opened URL: <a href="{escape(url)}">{escape(url)}</a></p>
  <p class="muted">Sign in yourself, paste the prepared prompt, then import the answer back into task {escape(task_id)}.</p>
</section>"""
    return page("Open Chat", body)


def error_page(status: int, message: str) -> str:
    return page(f"Error {status}", f"<section class=\"panel\"><pre>{escape(message)}</pre></section>")
