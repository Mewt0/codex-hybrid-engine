# PROJECT CONFORMITY AUDIT

**Project:** Codex Hybrid Engine / Codex Hybrid Game Development Studio  
**Audit date:** 2026-10-08  
**Workspace:** `F:\codex-hybrid-engine`  
**Scope:** objective conformity audit against the pasted Master Project Vision. No code changes were made during this audit.

## Executive Summary

Codex Hybrid Engine is a compact, working Python CLI with strong safety fundamentals: task state, Git-based review/apply, isolated validation copies, provider adapters, Browser AI Bridge, local skill/design prompts, repo-map heuristics, and Visual QA screenshot support. The current implementation is much closer to a conservative MVP than to the full "Game Development Studio" vision.

The strongest areas are Python core, path/security gates, Browser Bridge local workflow, and test coverage. The weakest areas are real multi-provider integration, PHP/MySQL functional QA, interactive Playwright-style testing, full project intelligence, and true subagent orchestration.

Overall confirmed conformity: **57 / 100**.

## Commands Run

```powershell
git status --short
rg --files
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m hybrid.cli --project . doctor
.\.venv\Scripts\python.exe -m hybrid.cli --project . providers
.\.venv\Scripts\python.exe -m hybrid.cli --project . browser providers
.\.venv\Scripts\python.exe -m hybrid.cli --project . skills --pack
.\.venv\Scripts\python.exe -m hybrid.cli --project . context show
.\.venv\Scripts\python.exe -m hybrid.cli --project . visual doctor
.\.venv\Scripts\python.exe -m hybrid.cli --project . map build --force
```

## Git Status

```text
?? demo_php/
```

The repository has one untracked directory, `demo_php/`. No tracked source changes were introduced by this audit except this report file.

## Project Structure

```text
F:\codex-hybrid-engine
|-- AGENTS.md
|-- ARCHITECTURE.md
|-- CONFIGURATION.md
|-- INSTALL.md
|-- README.md
|-- TESTING.md
|-- pyproject.toml
|-- config/
|   `-- settings.example.yaml
|-- ai-stack/
|   |-- PROJECT_CONTEXT.md
|   |-- design/
|   |   |-- MASTER.md
|   |   |-- COLORS.md
|   |   |-- TYPOGRAPHY.md
|   |   |-- COMPONENTS.md
|   |   |-- LAYOUTS.md
|   |   |-- ANIMATIONS.md
|   |   `-- SCREEN_REFERENCE.md
|   |-- profiles/
|   |   |-- frontend.yaml
|   |   |-- backend-php.yaml
|   |   |-- database.yaml
|   |   `-- fullstack-game.yaml
|   `-- skills/
|       |-- beautiful-game-ui/SKILL.md
|       |-- browser-testing/SKILL.md
|       |-- frontend-development/SKILL.md
|       |-- mysql-database/SKILL.md
|       |-- php-legacy/SKILL.md
|       |-- security-review/SKILL.md
|       `-- systematic-debugging/SKILL.md
|-- hybrid/
|   |-- cli.py
|   |-- config.py
|   |-- controller.py
|   |-- state.py
|   |-- tasks.py
|   |-- report.py
|   |-- providers/
|   |   |-- codex.py
|   |   |-- groq.py
|   |   |-- openrouter.py
|   |   |-- mock.py
|   |   `-- base.py
|   |-- browser_bridge/
|   |   |-- controller.py
|   |   |-- prompt_builder.py
|   |   |-- response_parser.py
|   |   |-- sessions.py
|   |   |-- errors.py
|   |   `-- providers/
|   |       |-- base.py
|   |       |-- chatgpt_web.py
|   |       `-- deepseek_web.py
|   |-- context/
|   |   |-- __init__.py
|   |   |-- file_context.py
|   |   `-- repo_map.py
|   |-- execution/
|   |   `-- worktree.py
|   |-- integrations/
|   |   `-- deepseek_harness.py
|   |-- quality/
|   |   `-- checks.py
|   `-- visual/
|       |-- driver.py
|       `-- engine.py
|-- docs/
|   |-- BROWSER_BRIDGE.md
|   |-- VISUAL_QA.md
|   |-- INSTALL_WINDOWS_WSL.md
|   `-- QA_ROUND_5.md
|-- tests/
|   |-- test_browser_bridge.py
|   |-- test_context_skills.py
|   |-- test_engine.py
|   |-- test_harness_adapter.py
|   |-- test_local_ui.py
|   |-- test_qa3_regressions.py
|   |-- test_qa4_regressions.py
|   |-- test_repo_map.py
|   |-- test_report.py
|   |-- test_security_regressions.py
|   `-- test_visual_qa.py
|-- tools/
|   |-- demo_browser_bridge.py
|   |-- probe_agent_browser.py
|   `-- smoke_visual_qa.py
`-- outbox/
```

## Test Results

```text
119 passed in 51.62s
```

The test suite was run with `.venv\Scripts\python.exe`. Global `python` does not have pytest installed, but the project virtual environment does.

## Dependency and Tool Check

| Dependency | Result |
|---|---|
| Python | `C:\Program Files\Python312\python.exe`, version `3.12.10`; `.venv` also `3.12.10` |
| Git | `C:\Program Files\Git\cmd\git.exe`, version `2.55.0.windows.3` |
| pytest | installed in `.venv`, version `9.1.1` |
| PyYAML | installed in `.venv`, version `6.0.3` |
| PHP CLI | NOT FOUND |
| Node.js | `C:\Program Files\nodejs\node.exe`, version `v24.19.0` |
| npm | `C:\Program Files\nodejs\npm.ps1`, version `11.17.0` |
| Codex CLI | `C:\Users\grut\AppData\Local\OpenAI\Codex\bin\9691020b546a15b2\codex.exe`, version `codex-cli 0.162.0-alpha.2` |
| Playwright CLI | NOT FOUND |
| Python `playwright` package | NOT FOUND |
| Chromium/Chrome | available via `C:\Users\grut\.agent-browser\browsers\chrome-155.0.8059.39\chrome.exe` |
| Composer | NOT FOUND |
| PHPUnit | NOT FOUND |
| PHPStan | NOT FOUND |
| ESLint | NOT FOUND |
| DeepSeek Harness SDK | Python module `deepseek_harness_sdk` NOT FOUND |

This is the Windows environment visible to the audit. WSL2 Ubuntu was not separately inspected.

## Conformity Matrix

| Component | Planned | Implemented | Status | Evidence | Missing |
|---|---|---|---|---|---|
| Python Core | Compact controller for tasks/providers/apply | CLI, config, state, tasks, controller | WORKING | `hybrid/cli.py`, `hybrid/controller.py`, `hybrid/state.py`, `tests/test_engine.py`; 119 tests pass | More end-to-end real project acceptance tests |
| Task Controller | classify, route, run, validate, review, apply | Present | WORKING | `Controller.run`, `_validate_patch_on_temp`, `apply`; `tests/test_engine.py`, `tests/test_qa3_regressions.py`, `tests/test_qa4_regressions.py` | No persistent queue or scheduler |
| FAST MODE | Quick changes without direct main-tree agent writes | Agent fast mode uses temp copy; model patch validation | WORKING | `Controller.run`, `test_nested_new_file_full_cycle` | Naming is implemented but not deeply documented as separate architecture |
| SAFE MODE | Git worktree isolation | Present | WORKING | `worktree.create_worktree`, `Controller.run(mode="safe")` | Git worktree is not OS sandbox |
| JSON State Store | Atomic task state | Present | WORKING | `StateStore._write_all`, `tests/test_browser_bridge.py::test_state_survives_restart` | No multi-file transaction across all artifacts |
| Git Review / Apply | Diff review and explicit approval | Present | WORKING | `Controller.diff`, `Controller.apply`; `hybrid review`, `hybrid apply --yes` | No GUI review |
| Codex Provider | Main coding agent | Adapter invokes `codex exec` | IMPLEMENTED | `hybrid/providers/codex.py`; `hybrid providers` says available | Real authenticated coding task not run in this audit |
| Groq Provider | Free/cheap model provider | Adapter exists, official endpoint guarded | IMPLEMENTED | `hybrid/providers/groq.py`; unavailable because `GROQ_API_KEY` unset | No live API test; model IDs not verified |
| OpenRouter Provider | Optional free routes | Adapter exists, disabled by default | IMPLEMENTED | `hybrid/providers/openrouter.py`; unavailable because disabled/key unset | No live API test |
| DeepSeek Harness | Optional subagent infrastructure | Disabled adapter with SDK guard | PARTIAL | `hybrid/integrations/deepseek_harness.py`, `tests/test_harness_adapter.py` | SDK missing; no real subagent workflow |
| DeepSeek Web | Manual browser relay | Provider exists and CLI-connected | WORKING for relay | `hybrid/browser_bridge/providers/deepseek_web.py`; `hybrid browser providers` | No autonomous web interaction |
| ChatGPT Web | Manual browser relay/review | Provider exists and CLI-connected | WORKING for relay | `hybrid/browser_bridge/providers/chatgpt_web.py`; `prepare_review` | No autonomous web interaction; account/model availability not checked |
| Unified Skills Layer | Shared skills for all models | Local `ai-stack/skills`, loader, profiles | PARTIAL | `ContextBuilder`, `SkillLibrary`, `hybrid skills --pack` finds 7 skills | External planned skills not installed; no version metadata |
| Design Memory | Shared design system | Markdown design files loaded into frontend/fullstack/review packs | PARTIAL | `ai-stack/design/*.md`, `ContextBuilder._design_block`, `DESIGN_FILES` | No structured tokens/CSS variable sync/update workflow |
| Project Intelligence | Understand PHP/JS/SQL dependencies | Regex RepoMap over allowed files | PARTIAL | `hybrid/context/repo_map.py`, `tests/test_repo_map.py` | No tree-sitter, LSP, SQL schema analysis, full include graph |
| Context Builder | Bounded context pack | Present | WORKING | `ContextBuilder.build`, `file_context.allowed_files`, `tests/test_context_skills.py` | Default allowed files is empty, so real target projects need trusted config |
| Quality Engine | path/dependency/syntax/review checks | Present | PARTIAL | `hybrid/quality/checks.py`, `run_quality`, `validate_dependencies` | No PHPUnit/PHPStan/ESLint integration; no SQL checks |
| QA5 | `.hybrid`, ignored dirs, apply blocking | Regressions covered | WORKING | `docs/QA_ROUND_5.md`, `tests/test_browser_bridge.py` QA5 tests, 119 tests pass | Multi-file artifact transaction remains open |
| Visual QA | Browser screenshots and responsive checks | Present with headless Chrome | PARTIAL | `hybrid/visual/engine.py`, `driver.py`, `hybrid visual doctor` available | Not Playwright; no click/form flows; failed requests limited by driver |
| Functional QA | Interface, API, SQL operations | Mostly absent | MISSING/PARTIAL | Basic syntax checks only in `run_quality` | No scenario runner, no DB fixture, no HTTP endpoint tests |
| Reports | Reviewable task report | Present | WORKING | `hybrid/report.py`, `tests/test_report.py` | Report quality depends on checks actually run |
| Browser Bridge | prompt -> relay -> import -> validate -> review -> apply | Present and tested | WORKING for local relay | `hybrid/browser_bridge/*`, `docs/BROWSER_BRIDGE.md`, `tests/test_browser_bridge.py` | Human must perform web interaction |
| Subagents | Explore/Design/Review/Visual agents | Harness adapter only | PARTIAL/STUB | `DeepSeekHarnessAdapter`; tests use fake SDK | No named agents, no conflict management, no result merge |
| Installation scripts | Setup for Windows/WSL | Docs only | PARTIAL | `INSTALL.md`, `docs/INSTALL_WINDOWS_WSL.md`, `pyproject.toml` | No robust installer/bootstrap script |

## AI Providers

| Provider | Adapter | Real call path | Context transfer | Patch result | Error handling | Integration tests | Mock? | Auth needed |
|---|---|---|---|---|---|---|---|---|
| Codex CLI | Yes | `subprocess.run([codex, "exec", prompt])` | Works through cwd plus prompt; not full ContextPack | Agent writes files, controller diffs | timeout and command validation | Unit tests with executable stubs | No | User must have Codex CLI authenticated |
| Groq | Yes | HTTPS official `api.groq.com/openai/v1` | `_target_files(..., cloud=True)` only allowed files | Model expected to return unified diff | key missing, URL guard, redirect refusal, redacted errors | Security/unit tests, no live call | No | `GROQ_API_KEY` |
| OpenRouter | Yes | HTTPS official `openrouter.ai/api/v1` | Same patch prompt as Groq | Model expected to return unified diff | key missing, URL guard, redirect refusal | Unit-level code only; no live call observed | No | `OPENROUTER_API_KEY`; disabled by default |
| DeepSeek Harness | Adapter only | SDK import and `run/run_task` if enabled | Description/cwd/safe env | Raw output only | disabled/missing SDK/timeout/parallel guard | Fake SDK tests | Yes, in tests | SDK/config needed |
| DeepSeek Web | Yes | `webbrowser.open("https://chat.deepseek.com")` | ContextPack rendered into prompt | Imported answer parsed/validated | response parser, repeat import, patch validation | Browser bridge tests | No | Human web login |
| ChatGPT Web | Yes | `webbrowser.open("https://chatgpt.com")` | ContextPack rendered into prompt | Imported answer parsed/validated | same as bridge | Browser bridge tests | No | Human web login |

No paid API calls were made.

## Unified Skills Layer

Installed project skills:

| Skill | Repository/version | Path | Codex availability | Hybrid availability | Tests |
|---|---|---|---|---|---|
| `beautiful-game-ui` | local project skill, no external version metadata | `ai-stack/skills/beautiful-game-ui/SKILL.md` | Yes as file context | Yes via `SkillLibrary` | `test_context_skills.py` |
| `browser-testing` | local project skill | `ai-stack/skills/browser-testing/SKILL.md` | Yes | Yes | `test_context_skills.py` |
| `frontend-development` | local project skill | `ai-stack/skills/frontend-development/SKILL.md` | Yes | Yes | `test_context_skills.py` |
| `mysql-database` | local project skill | `ai-stack/skills/mysql-database/SKILL.md` | Yes | Yes | `test_context_skills.py` |
| `php-legacy` | local project skill | `ai-stack/skills/php-legacy/SKILL.md` | Yes | Yes | `test_context_skills.py` |
| `security-review` | local project skill | `ai-stack/skills/security-review/SKILL.md` | Yes | Yes | `test_context_skills.py` |
| `systematic-debugging` | local project skill | `ai-stack/skills/systematic-debugging/SKILL.md` | Yes | Yes | `test_context_skills.py` |

Planned external skills from the vision (`UI/UX Pro Max`, Anthropic frontend design, OpenAI Playwright, Vercel web design guidelines, external security audit, PHP modernization, Superpowers variants) are **not installed as those upstream packages**. Their functionality is partially represented by local Markdown skills, but repository, version, and commit metadata are absent.

Adaptation for API models and Browser Relay is partial: `ContextBuilder` selects profile skills and `PromptBuilder` renders them, but there is no capability-aware transformation beyond prompt text.

## Design Memory

Status: **PARTIAL**.

Evidence:

- Design files exist in `ai-stack/design/`.
- `ContextBuilder.DESIGN_FILES` includes `MASTER.md`, `COLORS.md`, `TYPOGRAPHY.md`, `COMPONENTS.md`, `LAYOUTS.md`, `ANIMATIONS.md`.
- `ContextBuilder.build()` includes design for `frontend`, `fullstack-game`, and `review`.
- `hybrid skills --pack` showed `sections: design, project_context`.

Limitations:

- Design Memory is Markdown-only.
- There is no structured token registry, no CSS variable extraction, and no workflow that updates design memory before component changes.
- `SCREEN_REFERENCE.md` exists but is not loaded by `DESIGN_FILES`.
- Design rules persist as files, but no enforcement exists beyond prompts and visual review.

## Project Intelligence

Status: **PARTIAL**.

Evidence:

- `RepoMapBuilder` parses PHP functions/classes/constants/includes, JS functions/fetch endpoints, CSS imports/classes using regular expressions.
- It can mark PHP include and JS endpoint relationships as dependent.
- Tests cover PHP include, JS AJAX endpoint matching, heavy directory skipping, cache invalidation, and context pack repo-map use.

Actual current project run:

```text
Built repo map: F:\codex-hybrid-engine\.hybrid\repo-map.json
files: 0
relations: 0 relevant of 0
```

Reason: default `context.allowed_files` is empty, and project config cannot widen it. A trusted user config must explicitly allow files before cloud/browser context or repo map content is populated.

Missing:

- No tree-sitter.
- No LSP.
- No full PHP include resolution beyond quoted literals.
- No SQL schema/table understanding.
- No MySQL migration/introspection.
- No full AJAX contract graph.

## Quality Engine

Status: **PARTIAL but security-conscious**.

Working:

- `git apply --check` in temporary copy.
- Git-derived affected paths via `git apply --cached --intent-to-add` and `git diff --cached --name-status`.
- Path boundary checks, forbidden paths, sensitive markers, symlink detection.
- New dependency detection for `package.json` and `composer.json`.
- `git diff --check`.
- `php -l` when PHP exists.
- `node --check` when Node exists.
- Explicit manual review and apply confirmation.
- Apply revalidates patch artifact hash, base commit, clean worktree, paths, and `git apply --check`.

Gaps:

- PHP CLI is not installed here, so PHP syntax checks would be SKIP.
- No PHPUnit, PHPStan, Composer, ESLint, Playwright.
- No SQL syntax/data checks.
- No configured behavior test command.
- Functional QA for API/UI flows is not implemented.

## Browser AI Bridge

Status: **WORKING for manual relay**.

Evidence:

- CLI commands are connected in `hybrid/cli.py`: `browser providers`, `prepare`, `open`, `prompt`, `import`, `review`, `diff`, `request-review`, `history`, `cancel`.
- Providers available:

```text
chatgpt_web: https://chatgpt.com, relay
deepseek_web: https://chat.deepseek.com, relay
```

- `BrowserProvider.open_url()` only uses `webbrowser.open()` and refuses non-HTTPS URLs.
- No cookies/tokens/browser profile data are read or stored.
- `ResponseParser` parses sections and diff fences.
- Responses without diff are stored as analysis only.
- Repeat import is refused unless `--force`; CRLF-equivalent duplicate handling is covered.
- Imported patches go through path validation and temp Git validation before review.
- Apply remains the normal `hybrid apply TASK --yes`.

Limitations:

- This is not autonomous browser automation.
- Model choice/availability inside web chat is not verified.
- Human must copy/paste prompt and response.

## Subagents

Status: **PARTIAL/STUB**.

Evidence:

- `DeepSeekHarnessAdapter` exists.
- It supports enabled/disabled state, SDK import detection, timeout, recursion guard, max parallel guard, and safe environment filtering.
- Tests cover disabled adapter, missing SDK, fake SDK success/timeout, recursion, and key filtering.

Missing:

- No real `deepseek_harness_sdk` installed.
- No Explore Agent, Design Agent, Backend Researcher, Database Reviewer, Review Agent, or Visual QA Agent implementation.
- No subtask state model.
- No conflict detection for multiple agents editing overlapping files.
- No result merge protocol.

## Architectural Divergences

1. The vision describes a game development studio; the implementation is still a conservative local CLI MVP.
2. Project Intelligence is allow-list and regex based, not a full dependency graph.
3. Visual QA uses direct headless Chrome screenshots, not Playwright scenarios.
4. Functional QA is mostly absent beyond syntax/path/dependency checks.
5. Skills are local Markdown files, not the external skill packages listed in the vision.
6. DeepSeek Harness is an optional adapter, not real subagent orchestration.
7. Browser Bridge is intentionally manual relay, not autonomous web-chat control.
8. Design Memory is prompt context, not an enforceable design-token system.

## Duplicate or Overlapping Components

- `ai-stack/profiles/*.yaml` and `hybrid/context.PROFILES` overlap. Runtime uses the Python mapping for actual skill selection, while YAML files document profiles.
- `docs/QA_ROUND_5.md` and tests both document QA5; this is useful, but the docs are historical rather than executable.
- Visual QA has two browser drivers: `ChromeScreenshotDriver` and `AgentBrowserDriver`. This is intentional fallback, not harmful duplication.
- Repo-map artifacts also exist as `.codex-repomap.*` files, separate from `.hybrid/repo-map.json`; their relationship is not documented in runtime code.

## Security Findings

Confirmed protections:

- Mandatory `.env`, `.env.*`, `config/secrets/*`, and `tests/protected/*` forbidden paths are merged in `config.py`.
- Project config cannot widen `context.allowed_files` or redirect provider base URLs.
- Provider API keys are not forwarded to Codex or DeepSeek Harness SDK environments.
- Groq/OpenRouter keys are only sent to canonical HTTPS endpoints and redirects are refused.
- Browser Bridge does not read cookies, tokens, passwords, or browser profiles.
- Apply refuses dirty worktrees and changed base commits.

Remaining risks:

- Git worktree/temp copy is not an OS sandbox.
- State/artifact writes are individually atomic but not a single multi-file transaction.
- Agent providers can execute local tools through Codex; safety depends on Codex sandbox/approval and project guardrails.
- No real PHP/MySQL security integration tests exist because PHP/MySQL tooling is absent.

## Score

| Direction | Weight | Confirmed score | Rationale |
|---|---:|---:|---|
| Python Core and security | 20% | 17% | Core works, security regressions covered, 119 tests pass; not an OS sandbox and no multi-file transaction |
| Real AI providers | 20% | 8% | Codex CLI installed and adapters exist; Groq/OpenRouter/Harness not live-verified |
| Unified Skills and Design Memory | 20% | 12% | Local skills/design work in prompts; external skill packages/versioning/enforcement absent |
| PHP/JS/SQL Project Intelligence | 15% | 6% | Regex repo-map exists; no tree-sitter/LSP/SQL schema and default map is empty |
| Functional and Visual QA | 15% | 7% | Visual screenshots available; functional QA and Playwright absent |
| Browser AI Bridge | 10% | 7% | Manual relay cycle is implemented/tested; not autonomous and live web result not verified |
| **Total** | **100%** | **57%** | Conservative MVP with solid safety core, not yet full studio |

## Priority Plan

### P0 - Stability and Security

- Add a crash-recovery test for browser task metadata/index/review consistency.
- Keep QA5 regression tests mandatory.
- Document that `.hybrid/repo-map.json` is internal state and should not be included in task patches.

### P1 - Real Codex Integration

- Run one safe-mode Codex task against `demo_project` with Codex CLI and record the full result.
- Add an integration marker for live Codex tests so unit tests remain offline.
- Verify that Codex sandbox/approval behavior is not weakened by environment handling.

### P2 - Unified Skills and Design Memory

- Add version/source metadata to every installed skill.
- Decide whether planned external skills are installed packages or replaced by local equivalents.
- Include `SCREEN_REFERENCE.md` in frontend/fullstack design context or document why it is excluded.
- Add a design-token extraction/check step for CSS variables.

### P3 - Functional and Visual QA

- Install/verify PHP CLI, Composer, PHPUnit/PHPStan where relevant.
- Add a local HTTP server fixture for `demo_php`.
- Add browser interaction scenarios for inventory flows.
- Consider Playwright as a scenario runner; keep Chrome screenshot driver for cheap visual evidence.

### P4 - Project Intelligence

- Make repo-map build useful for real projects by guiding trusted `context.allowed_files` setup.
- Add SQL file/table extraction.
- Improve PHP include resolution beyond literal paths.
- Add JS fetch-to-PHP contract summaries.

### P5 - Browser AI Bridge

- Add an offline end-to-end demo test that prepares, imports, validates, reviews, and applies a simulated web answer.
- Surface Browser Bridge warnings more prominently in CLI review output.
- Keep it as a manual relay, not a replacement for Codex.

### P6 - DeepSeek Harness and Subagents

- Treat Harness as optional until the SDK and contract are real.
- Define a minimal subtask protocol before adding named agents.
- Add conflict prevention before enabling parallel editing.

## Final Assessment

The project already has a serious safety-first foundation: local state, provider guards, trusted context allow-listing, Git validation, explicit apply, Browser Bridge relay, design/skill prompt libraries, and a passing regression suite. It does **not** yet satisfy the full original game-studio vision because real multi-provider operation, functional PHP/MySQL QA, interactive browser testing, deep project intelligence, and subagent orchestration are either partial or missing.

The next best move is not a rewrite. Finish the real acceptance path on a safe PHP/JS demo game: one feature request, Codex safe-mode implementation, PHP/JS checks, local browser screenshots, report, diff review, and explicit apply. That will expose the remaining gaps faster than adding more abstractions.
