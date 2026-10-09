# AGENTS.md

This project is developed through **Codex Hybrid Engine**. Any agent working
here — Codex, a Groq/OpenRouter model, or a DeepSeek Harness subagent — follows
the same rules.

## Read before changing anything

1. `ai-stack/PROJECT_CONTEXT.md` — what the project is and its hard rules.
2. The profile for your task in `ai-stack/profiles/` (frontend, backend-php,
   database, fullstack-game).
3. The relevant skill in `ai-stack/skills/`.
4. `ai-stack/design/MASTER.md` before touching anything visual.

## Working agreement

- The engine never commits for you and never pushes.
- Changes are proposed as a patch in a Git worktree; a human applies them with
  `hybrid apply <TASK-ID> --yes`.
- Do not disable sandbox or approval mechanisms for delegated agents.
- Full access for direct Codex CLI sessions and for the engine's Codex provider is allowed only as described in `ai-stack/CODEX_CLI_FULL_ACCESS.md`.
- Do not add dependencies without an explicit task instruction.
- Do not send project files to a cloud provider; only files listed in the
  trusted `context.allowed_files` are sent.
- Keep the target stack: legacy PHP, plain JavaScript, MySQL. No framework
  migration unless the user asks for it.
- Report unexecuted checks as NOT RUN. Never claim a check you did not run.

## Definition of done

A task is done when the behaviour is implemented, the relevant checks ran, the
result is reviewable as a diff, and any visual change was verified in a browser.
