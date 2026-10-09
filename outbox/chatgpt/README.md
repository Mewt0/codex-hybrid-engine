# Очередь задач для ChatGPT

**Правило: один чат = одна задача.** Больше в чат ничего не докидывать, иначе
модель начнёт путать контекст.

## Порядок работы

1. Открываешь **новый** чат.
2. Вставляешь первым сообщением содержимое `00_HEADER.md`.
3. Вторым сообщением — содержимое одного файла задачи.
4. Получаешь ответ в формате `## FILE: путь` + код.
5. Присылаешь ответ мне. Я вставляю код в проект, гоняю тесты и говорю, что не так.

## Задачи (по убыванию пользы)

| # | Файл | Что даёт | Новые файлы |
|---|---|---|---|
| 1 | `TASK_STORE_RECOVERY.md` | Устойчивость хранилища к аварии, `browser verify/repair` | правки `sessions.py`, `cli.py`, новый тест |
| 2 | `TASK_FUNCTIONAL_QA.md` | Реальная проверка PHP-эндпоинта, а не только `php -l` | `quality/functional.py`, `quality/scenarios.py`, тест |
| 3 | `TASK_BROWSER_CONTEXT.md` | `hybrid browser context TASK-ID` — что уйдёт в чат | `browser_bridge/context_preview.py`, тест |
| 4 | `TASK_VISUAL_SCENARIOS.md` | Клики/формы/модалки в Visual QA | `visual/scenarios.py`, тест |
| 5 | `TASK_DESIGN_TOKENS.md` | Проверка CSS против Design Memory | `quality/design_tokens.py`, тест |
| 6 | `TASK_PHP_SQL_SKILL.md` | Навык `php-sql-contracts` + профили | markdown + тест |

## Почему именно эти

Пункты 1–2 закрывают находки аудита (надёжность хранилища и отсутствие
функциональной QA). Пункты 3–4 закрывают разрыв между планом и реализацией
(нет `browser context`; Visual QA без интерактива). Пункты 5–6 усиливают
профили PHP/SQL и дизайн-дисциплину.

## Что уже сделано, не заказывать

- QA5, LF-патчи, fetch объектов в клон, парсер патчей (обе стороны, регистр);
- Unified Skills, Design Memory, профили, `AGENTS.md`;
- Browser AI Bridge (DeepSeek Web + ChatGPT Web, relay);
- Visual QA скриншоты desktop/tablet/mobile; Repo Map; Harness adapter;
- TASK RESULT-отчёт; локальный Web Workspace (`hybrid ui`); PHP-демо `demo_php/`.
