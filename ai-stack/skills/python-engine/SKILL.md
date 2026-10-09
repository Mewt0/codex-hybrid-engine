---
name: python-engine
description: Rules for changing the engine's own Python modules without breaking its guarantees.
triggers: [python, модуль, рефактор, индекс, состояние, атомарн, тесты, cli, parse]
---
# Python engine work

Use when the task changes the engine itself (`hybrid/**`, `tests/**`).

## Invariants you must not break

- Only the standard library. A new dependency is a defect unless the task says otherwise.
- State and artifacts are written atomically: temp file + `os.replace`, LF newlines.
- A missing tool or an unexecuted check is reported as `SKIP`/`NOT RUN`, never `PASS`.
- Public behaviour of existing classes stays compatible: `StateStore`, `BrowserTaskStore`,
  `TaskRecord`, `Controller`, and the CLI subcommands other modules rely on.
- Never widen what may be read: the trusted `context.allowed_files` list is the only
  source for cloud/browser context.
- Secrets stay out of code, logs and artifacts.

## Change discipline

1. Read the module and its tests before editing; name the contract you must preserve.
2. Add the regression test first, then the fix. A fix without a failing test is unproven.
3. Keep functions small and single-purpose; extract to a module only when it earns its place.
4. Errors are explicit exception types, never a bare `Exception`.
5. Update the docstring when behaviour changes; keep comments about *why*, not *what*.

## Verification

- `pytest -q` must pass; report the exact count.
- A new CLI command must be covered by at least one test that calls `cli.main([...])`.
- Report honestly which checks you could not run.
