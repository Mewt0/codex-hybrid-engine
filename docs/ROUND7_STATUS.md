# Round 7 — статус безопасной интеграции Codex Hybrid Engine

**Дата:** 2026-10-09

**Репозиторий:** `F:\codex-hybrid-engine`, `master`, HEAD `fe1f37e17e3a229ff18f5090a5c44ac0344fabe3`

**Назначение:** дополнение к `docs/MASTER_CONFORMITY_RESULT.md` по состоянию после раунда 6.

## Итог

**Codex Hybrid Engine пока BLOCKED FOR SAFE EXECUTION на реальном PHP/JS-проекте.** Реальный Codex однажды подготовил проверяемый patch через Hybrid (`TASK-756955A7`), но он работал с `danger-full-access`. Этот режим не предоставляет Codex sandbox-изоляцию; изоляция Git worktree защищает исходный checkout от прямых записей, но не ограничивает процесс на уровне ОС. Поэтому успешный запуск не является доказательством безопасной работы.

Защищённый `workspace-write` на этой машине не подтверждён: известная ошибка Windows helper — `helper_unknown_error`. В раунде 7 новые реальные вызовы моделей и агентные задачи не запускались. Trusted-конфиг не менялся.

## Что исправлено в раунде 7

- Вывод Codex CLI теперь декодируется с `encoding="utf-8", errors="replace"` в `CodexProvider.execute()`, `CodexProvider.probe_write()` и реальных Codex-вызовах делегатора/preflight. Это не зависит от Windows code page и заменяет некорректные байты вместо `UnicodeDecodeError`.
- Настройки sandbox отражают источник `trusted_user` в `hybrid providers`. Проектный `config/settings.yaml` не может задать `sandbox` или `windows_sandbox`; regression test проверяет trusted override, отбрасывание project value и строку CLI.
- Документация `CodexProvider` явно указывает, что `danger-full-access` снимает sandbox Codex и не ограничивает процесс рабочим каталогом на уровне ОС.
- Основной `.venv` получил editable-установку проекта (`pip install -e .`); `hybrid.exe` запускается из основного окружения.

Файлы, затронутые этими исправлениями: `hybrid/config.py`, `hybrid/providers/codex.py`, `hybrid/integrations/codex_cli_delegate.py`, `tests/test_qa3_regressions.py`, `tests/test_conformity_regressions.py`. Их текущие diff уже содержат более ранние изменения; перед коммитом нужно отдельно просмотреть весь diff этих файлов.

## Проверки, выполненные сейчас

| Проверка | Результат |
|---|---|
| Полный `pytest -q` из основного `.venv` | **267 passed**, 127.60 с |
| Целевые regression tests | **29 passed**, включая UTF-8/не-ASCII и sandbox provenance |
| Offline/mock conformity E2E | **8 PASS / 0 FAIL**; запускался из временной копии пакета в `%TEMP%`, модельные API не вызывались |
| `hybrid.exe --help` из основного `.venv` | PASS |
| `hybrid doctor` | PASS: Python, Git, Codex CLI, PHP, Node обнаружены |
| `hybrid providers` | PASS; sandbox показан как `danger-full-access (trusted_user)`. Статус Codex — конфигурационный; живой вызов не выполнялся |
| Проверка Prompt Pack | PASS: skills реально включены для frontend (3), backend-PHP (3), database (2), fullstack-game (7) |
| `git diff --check` | PASS, диагностик diff нет; Git выдаёт только обычные LF/CRLF предупреждения |
| Проверка типовых credential/private-key шаблонов в изменённых текстовых файлах и staged diff | Совпадений нет. Это базовый автоматический поиск, не полный аудит секретов; бинарные изображения содержимым не проверялись |
| Defender | Только чтение статуса: `RealTimeProtectionEnabled=False`, `AntivirusEnabled=False`, `AMServiceEnabled=False`. Ничего не менялось и не восстанавливалось |
| Codex `workspace-write` и реальные модельные вызовы | **NOT RUN** в раунде 7; предыдущий handoff фиксирует отказ `helper_unknown_error` |
| Живой MySQL, WSL2, кросс-браузерные и Local UI проверки | **NOT RUN** в раунде 7 |

Offline E2E использовал disposable Git-репозитории: подтвердил `run → review → apply` с mock, отказ apply без `--yes`, отказ при подменённом patch и защиту пользовательской правки. Это проверка локального механизма Hybrid, а не Codex sandbox.

## Безопасность и поддерживаемые варианты восстановления

- `danger-full-access` не ограничивает Codex каталогом проекта. В handoff раунда 6 также указано, что `codex exec` сообщает `approval: never`; не считать approval дополнительной границей защиты для non-interactive исполнения.
- Официальная документация рекомендует Windows MXC на совместимом устройстве; classic `elevated` — поддерживаемый fallback с администраторской настройкой. Для degraded Windows sandbox описана команда TUI `/setup-default-sandbox`; документация также описывает `codex sandbox setup --elevated --user ... --codex-home ...` для развёртывания администратором. См. [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox) и [Developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli).
- В старом отчёте уже записан неуспешный локальный MXC smoke (ошибка файловой системы `G:` / os error 1005). Повторно не проверялся. Переустановку/перенастройку Codex и provisioning sandbox в этом раунде не запускал, чтобы не менять системную или пользовательскую конфигурацию.
- `unelevated` не использовать как исправление: отчёт фиксирует запись за пределами workspace, поэтому это не приемлемая граница изоляции.
- Defender ранее был вырезан/отключён. По прямому указанию пользователя он не включался и не восстанавливался; текущее выключенное состояние только прочитано.

## Codex task из раунда 6

`TASK-756955A7` по-прежнему `ready_for_review`, `error: None`, provider `codex`, изменён только `hello_hybrid.txt`; proposal сохранён в `.hybrid/tasks/TASK-756955A7/proposed.patch`. В раунде 7 он не запускался повторно и не применялся. Успех был получен при `danger-full-access`, поэтому не закрывает критерий безопасного исполнения.

## Skills

В `ai-stack/skills/` обнаружено 8 локальных skills; они загружаются Prompt Pack и попадают в перечисленные выше профили. Это подтверждено сборкой pack в текущем коде.

Внешние материалы не копировались и не подключались:

- `frontend-design`: локальный источник у пользователя, Apache-2.0; версия в `SKILL.md` не указана.
- `systematic-debugging`, `verification-before-completion`, `test-driven-development`: Superpowers **6.3.0**, MIT; найдены во временном `.codex/.tmp` плагине. Их не переносил, поскольку путь временный; встроенный проектный `systematic-debugging` уже включён в prompt packs.
- `ui-ux-pro-max`: лицензия самого навыка не найдена — не подключать.
- `web-design-guidelines`, `security-audit`, `php-modernization`: по прошлому рекурсивному аудиту отсутствуют; повторный поиск в раунде 7 не выполнялся.

## Read-only аудит рабочего дерева

До добавления этого статус-файла `git status --short` показывал 62 компактные записи: 2 staged удаления, 31 unstaged tracked file и 29 untracked entries (папки скриншотов и сайтов отображаются одной записью; в развёрнутом списке — 38 untracked файлов). Добавление `docs/ROUND7_STATUS.md` даёт 63 компактные записи. Не было `commit`, `reset`, `clean`, `hybrid apply` или удаления файлов в основном репозитории.

Staged удаления, требующие решения владельца: `.chatgpt-prompt-1.md`, `.session-check.png`.

Логические группы для будущего отдельного review/коммита:

1. Codex/config/security и delegated CLI: `hybrid/config.py`, `hybrid/providers/codex.py`, `hybrid/integrations/codex_cli_delegate.py`, соответствующие тесты, `AGENTS.md`, `ai-stack/PROJECT_CONTEXT.md`, `ai-stack/CODEX_CLI_FULL_ACCESS.md`.
2. Browser Bridge: `hybrid/browser_bridge/`, `hybrid/browser_bridge/sites/`, `docs/BROWSER_BRIDGE.md`, browser-related tests и `tools/smoke_browser_state.py` / `tools/inspect_live_dom.py`.
3. PHP inventory demo: `demo_php/` и профиль/документация, напрямую связанные с демо.
4. Visual QA: `hybrid/visual/`, `ai-stack/design/SCREEN_REFERENCE.md`, `ai-stack/design/screens/`, `docs/visual-qa/`, `docs/VISUAL_QA_DEMO_INVENTORY.md`, `tools/visual_qa_inventory.py`, visual tests.
5. Runtime/provider/repo-map: `hybrid/php_runtime.py`, `hybrid/providers/status.py`, `hybrid/context/`, профильные и security regression tests.
6. Conformity reports/evidence and handoffs: `docs/CONFORMITY_*`, `docs/MASTER_CONFORMITY_RESULT.md`, `docs/ROADMAP_FULL.md`, JSON evidence, `outbox/`, `error.log`.
7. Staged deletions — отдельная группа, решение только после просмотра владельцем.

Группировка предварительная: git не указывает авторов незакоммиченных файлов, поэтому отнести каждый файл к конкретной сессии достоверно нельзя. Неудачный worktree `TASK-9059933A` сохранён; в нём остаются изменения `AGENTS.md`, `ai-stack/PROJECT_CONTEXT.md` и untracked `ai-stack/CODEX_CLI_FULL_ACCESS.md`. Он не удалялся. Его task record — `failed`, patch artifact отсутствует.

## Что нужно для закрытия P0 и готовности

1. Владелец/администратор выбирает и настраивает поддерживаемый Windows sandbox (MXC при совместимости или elevated provisioning); не использовать full access и не ослаблять Defender.
2. После ремонта выполнить только ограниченный smoke `workspace-write` в disposable repo и убедиться, что запись за пределами sandbox запрещена; это потребует отдельного разрешения на реальный запуск CLI.
3. Просмотреть 62 исходные записи дерева и отдельно решить staged deletions; после получения чистой базы review/apply проверить отдельно. Ничего из этих записей не очищать автоматически.
4. Для проверки реальной PHP/JS-игры подготовить разрешённый тестовый MySQL, когда база нужна; WSL2 не требуется для native Windows workflow.
5. После sandbox-приёмки отдельно оценить внешние skills из постоянных лицензированных источников. До этого не подключать UI/UX Pro Max и отсутствующие skills.

**Готовность к безопасной автономной работе с реальной PHP/JS-игрой: НЕТ.** Основной CLI теперь установлен, локальные E2E и тесты проходят, но ОС-уровень sandbox Codex не восстановлен и не подтверждён.
