# Codex Hybrid Engine

Compact local Python CLI for routing development tasks between Codex CLI and optional OpenAI-compatible model providers.

Полная карта подсистем, целевой результат и этапы завершения проекта: [docs/ROADMAP_FULL.md](docs/ROADMAP_FULL.md).

Implemented commands:

```bash
hybrid doctor
hybrid init
hybrid providers
hybrid context preview
hybrid context show
hybrid skills [--pack]
hybrid profile [--task "описание задачи"]
hybrid run "Fix a small bug" --mode safe
hybrid run "Update CSS" --mode fast --dry-run
hybrid status TASK-XXXXXXXX
hybrid review TASK-XXXXXXXX
hybrid apply TASK-XXXXXXXX --yes
hybrid browser providers
hybrid browser prepare "Сделай инвентарь" --provider deepseek --profile frontend
hybrid browser open BTASK-XXXXXXXX
hybrid browser prompt BTASK-XXXXXXXX
hybrid browser import BTASK-XXXXXXXX --file answer.md
hybrid browser review BTASK-XXXXXXXX
hybrid browser request-review BTASK-XXXXXXXX
hybrid browser history
hybrid browser cancel BTASK-XXXXXXXX
hybrid browser launch                    # once: open the shared Chrome profile and sign in
hybrid browser status
hybrid browser at --url https://chatgpt.com/
hybrid browser read --json
hybrid browser say "текст" --send
hybrid browser chat --task BTASK-XXXXXXXX --send --new-conversation
```

The MVP is conservative by default: paid API use is disabled, approval is required, retries are limited, fast mode stores a per-task patch artifact, and safe mode writes changes into a Git worktree.

## Browser AI Bridge

No API key? Work with a strong model through its official web chat. See
[docs/BROWSER_BRIDGE.md](docs/BROWSER_BRIDGE.md).

```bash
hybrid browser prepare "Улучши игровую панель и сделай её адаптивной" --provider deepseek
hybrid browser open BTASK-XXXXXXXX          # sign in yourself, paste the prompt, copy the answer
hybrid browser import BTASK-XXXXXXXX --file answer.md
hybrid browser review BTASK-XXXXXXXX
hybrid apply TASK-XXXXXXXX --yes
```

Try the whole cycle offline with a simulated answer:

```bash
python tools/demo_browser_bridge.py
```

### Manual relay vs. automation mode

Two different modes share one command group, and they have different trust
models:

| Mode | Commands | Who acts |
|---|---|---|
| **Manual relay** (default, unchanged) | `browser prepare / open / prompt / import / review / diff / request-review` | You paste the prompt and copy the answer back. Nothing is submitted for you. |
| **Automation** (opt-in, live Chrome over CDP) | `browser launch / status / at / read / say / chat` | The engine types into your signed-in tab and reads the answer, but only with an explicit `--send`. |

Automation rules that are enforced in code, not by convention:

- `browser chat` is a **dry run without `--send`**: the prompt goes into the box and stops there.
- An already validated result is **never replaced implicitly**; that needs `--force-import`.
- An answer that was still streaming when `--timeout` expired is refused; that needs `--allow-partial`.
- The answer is read only from the assistant message that appeared *after* the submit.
- Login wall / CAPTCHA / rate limit stop the run before anything is typed.
- New chats are archived after a successful import to keep the sidebar tidy; `--continue` chats are never archived. Use `--keep-conversation` to retain a newly created chat.

Browser artifacts live in `.hybrid/tasks/<TASK-ID>/browser/` (`state.json`,
`timing.json`, `prompt.json`, `answer.json`, and on failure `screenshot.png`
plus a **redacted** `dom-snippet.html`). `.hybrid/` is gitignored and never
leaves your machine; `screenshot.png` shows page pixels, so treat it as you
would a screenshot of the conversation.

If a run stops on a login wall, a CAPTCHA or a rate limit: the message says so,
nothing was sent, artifacts are saved. Sign in again in the shared window
(`hybrid browser launch`), solve the challenge yourself in that window, or wait
out the limit — the engine deliberately does not try to get around either.

## Visual QA

Check a local page in a real browser: screenshots at 390x844, 768x1024 and
1440x900, page console errors, failed requests, and a report stored with the
task. See [docs/VISUAL_QA.md](docs/VISUAL_QA.md).

```bash
hybrid visual doctor
hybrid visual run TASK-XXXXXXXX --url http://localhost:8000/index.php
```

## Task Result report

```bash
hybrid report TASK-XXXXXXXX          # markdown report + saved report.json/report.md
hybrid report TASK-XXXXXXXX --json
```

The report always lists every field of the canonical shape and marks checks that
did not run as `NOT RUN` instead of hiding them.

## Unified Skills and Design Memory
`ai-stack/` is the canonical instruction library shared by every provider:

- `ai-stack/PROJECT_CONTEXT.md` — what the project is and its hard rules;
- `ai-stack/skills/*/SKILL.md` — reusable skills (`beautiful-game-ui`,
  `frontend-development`, `php-legacy`, `mysql-database`, `security-review`,
  `browser-testing`, `systematic-debugging`);
- `ai-stack/design/*.md` — design memory (colors, typography, components,
  layouts, animations, screen reference);
- `ai-stack/profiles/*.yaml` — task profiles (`frontend`, `backend-php`,
  `database`, `fullstack-game`).

Only skills relevant to the task profile enter the prompt, and only files from
the trusted `context.allowed_files` list enter the context.

## Quick Start

```bash
cd codex-hybrid-engine
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
hybrid doctor
hybrid init
hybrid providers
```

Run a dry plan:

```bash
hybrid run "Обнови CSS кнопки" --mode fast --dry-run
```

Run against the demo fixture without cloud calls:

```bash
hybrid --project demo_project run "Fix broken label" --mode safe --provider mock
hybrid --project demo_project review TASK-XXXXXXXX
hybrid --project demo_project apply TASK-XXXXXXXX --yes
```

Replace `TASK-XXXXXXXX` with the task id printed by `run`.

## Providers

`codex` uses `codex exec` when the Codex CLI is installed and authenticated by the user. The engine does not alter Codex auth and does not disable sandbox or approval mechanisms.

`groq` uses the OpenAI-compatible API. Set `GROQ_API_KEY` in the environment. The configured model IDs are examples and should be verified with `hybrid providers` and Groq `/models` before real use.

`deepseek_harness` is present only as a disabled optional integration adapter. It is not reported as working unless a supported local CLI contract is verified.

## Safety Notes

Hybrid Engine requires an existing Git repository and refuses to run development tasks in a plain directory. It does not run `git init`, `git add .`, or `git commit` in the user project.

FAST MODE does not let agent providers write directly to the main project directory. Agent output is produced in an isolated temporary copy and stored as `.hybrid/tasks/<TASK-ID>/proposed.patch`.

`apply` requires explicit confirmation with `--yes`, rechecks protected paths, verifies that the patch artifact has not changed since review, checks for conflicts with `git apply --check`, and refuses to apply over local user changes.

These are Git and program-level guardrails, not a full OS sandbox for untrusted code. Git worktrees and temporary copies reduce accidental damage but do not replace filesystem sandboxing.

## QA Round 2 Update

See [QA_ROUND_2.md](QA_ROUND_2.md) for the security fixes, reproducible
demonstrations and limitations. Groq file context now requires an explicit
`context.allowed_files` list; the default sends no project files.

## QA Round 3 Update

See [QA_ROUND_3.md](QA_ROUND_3.md) for the patch-path, trusted configuration
and Groq API-key protections added after the third audit round.

Project YAML can no longer set `providers.codex.command` or redirect
`providers.groq.base_url`. Custom Codex executable paths and custom Groq base
URLs must come from trusted user configuration, and `GROQ_API_KEY` is only sent
to `https://api.groq.com/openai/v1`.
