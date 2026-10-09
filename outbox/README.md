# Очередь задач для ChatGPT (свежий чат на каждую задачу)

Правило: **один чат = одна задача**. В начало чата вставляешь
`00_BOILERPLATE.md`, затем файл задачи. Так контекст не забивается, а ответ
приходит в формате `## FILE: ...`, который сразу вставляется в репозиторий.

| Файл | Задача | Статус |
|---|---|---|
| `TASK_VISUAL_QA.md` | Visual QA Engine (PHASE 3) | сделано в движке, годится как независимое ревью |
| `TASK_REPO_MAP.md` | Repo Map (PHASE 4) | сделано в движке, годится как независимое ревью |
| `TASK_HARNESS.md` | DeepSeek Harness adapter (PHASE 5) | сделано в движке, годится как независимое ревью |
| `TASK_REVIEW.md` | Независимое ревью Browser AI Bridge | **актуально, нужен свежий чат** |
| `BROWSER_BRIDGE_TASK.md` | Исходное ТЗ моста | ответ получен, использован как ревью |

## Что уже реализовано движком (не заказывать заново)

- PHASE 0 — контроль `.hybrid/`, `dist/`, `node_modules/`, LF-патчи, честные проверки;
- Browser AI Bridge: DeepSeek Web + ChatGPT Web, relay-режим, import/review/apply;
- Unified Skills (7 навыков), Design Memory (7 файлов), 4 профиля, `AGENTS.md`;
- Visual QA: реальные скриншоты desktop/tablet/mobile через headless Chrome;
- Repo Map: эвристика связей PHP/JS/CSS/SQL с тремя состояниями зависимости;
- Harness adapter: необязательный, по умолчанию выключен;
- TASK RESULT отчёт (`hybrid report`).

## Как принимать ответ от ChatGPT

1. Скопируй код из блоков `## FILE: <путь>` в соответствующие файлы.
2. Запусти `F:\codex-hybrid-engine\.venv\Scripts\python.exe -m pytest -q`.
3. Если тесты падают — не правь тесты, принеси ошибку обратно в тот же чат.
4. Только после зелёного прогона — коммит в ветку задачи.
