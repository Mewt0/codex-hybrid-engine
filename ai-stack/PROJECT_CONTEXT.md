# Project Context

Canonical project intelligence for Codex Hybrid Engine itself. Every provider
(Codex, Groq, OpenRouter, future Harness) receives this file through the
Context Pack, so all agents share one description of the project.

## What this project is

Codex Hybrid Engine is a compact Python CLI that routes development tasks
between a strong coding agent (Codex CLI) and cheap/free OpenAI-compatible
models, with Git-worktree isolation, quality gates and explicit user approval
before any change reaches the main branch.

## Hard rules

- Never disable sandbox or approval mechanisms for delegated agents.
- Codex exception: full access is allowed for direct Codex CLI sessions on explicit user request, and for the engine's Codex provider only when the trusted user config selects it. Never use `--dangerously-bypass-approvals-and-sandbox`. See `ai-stack/CODEX_CLI_FULL_ACCESS.md`.
- Never call a paid API unless `budget.allow_paid_api` is explicitly true.
- Never apply changes to the project without `hybrid apply <TASK-ID> --yes`.
- Never commit on behalf of the user.
- Never send project files to a cloud provider unless the file is explicitly
  listed in the trusted `context.allowed_files`.
- Project configuration is untrusted: it cannot redirect API keys, cannot
  change the Codex executable and cannot widen the context.

## Entry points

| Path | Role |
|---|---|
| `hybrid/cli.py` | CLI surface (`doctor`, `run`, `review`, `apply`, `context`, `skills`, `profile`) |
| `hybrid/controller.py` | Orchestration: classify → select provider → execute → validate → review |
| `hybrid/providers/` | Provider adapters (`codex`, `groq`, `openrouter`, `mock`) |
| `hybrid/execution/worktree.py` | Git worktree isolation, diffs, cleanliness checks |
| `hybrid/quality/checks.py` | Path, dependency, syntax and review gates |
| `hybrid/context/` | Unified Skills Layer, Design Memory, Context Pack builder |

## Engineering conventions

- Python 3.11+, `from __future__ import annotations`, type hints on public code.
- No new runtime dependency without `architecture.allow_new_dependencies`.
- Tests live in `tests/` and must pass with `pytest -q`.
- Patches are always written LF-only; CRLF breaks `git apply --cached`.
