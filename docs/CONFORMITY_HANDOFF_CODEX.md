# HANDOFF → CODEX: MASTER CONFORMITY FIX, фазы 3–10

**Кому:** Codex.
**От:** агент, выполнивший Phase 0, 1 и диагностику Phase 2.
**Дата:** 2026-10-09.
**Репозиторий:** `F:\codex-hybrid-engine`, ветка `master`, HEAD `fe1f37e`
(рабочее дерево содержит незакоммиченную работу — **не коммить без разрешения владельца**).

Читать вместе с:
- `docs/CONFORMITY_BASELINE.md` — точная исходная точка и все блокеры;
- `docs/MASTER_CONFORMITY_RESULT.md` — матрица соответствия A–M.

---

## 0. Что уже сделано (не переделывать)

| Фаза | Статус | Артефакт |
|---|---|---|
| 0. Baseline | COMPLETE | `docs/CONFORMITY_BASELINE.md` |
| 1. Core + QA5 + Git safety | COMPLETE | `tools/conformity_e2e.py` (8/8), `tools/conformity_git_safety.py` (8/8) |
| 1.4 FAST MODE изоляция | COMPLETE | сценарий 1.4 в E2E |
| 2. Codex CLI диагностика | BLOCKED, причина найдена | `MASTER_CONFORMITY_RESULT.md` § D.1 |
| 6. Browser/Visual/Functional QA | COMPLETE для трёх viewport | `tools/visual_qa_inventory.py` (16/16), `docs/VISUAL_QA_DEMO_INVENTORY.md` |

**Тесты:** `238 passed`, 0 FAIL.
**Visual QA:** `16 passed`, 0 FAIL — это реальный Chrome против реального PHP.

**Исправлен `hybrid/cli.py`:** `doctor` теперь использует `php_binary()` и `_resolve_tool()`
для абсолютных доверенных путей. Было `PHP: NOT FOUND` / `Codex CLI: NOT FOUND`,
стало реальные пути. **Не откатывать** — закреплено 8 тестами.

**Устаревшие утверждения, которые нельзя повторять как факт:**
- «PHP: NOT FOUND» — неверно, PHP 8.5.11 есть в OSPanel и движок его находит.
- «224 passed» — устарело.
- «QA5 — набор проверок в `quality/checks.py`» — неверно, см. baseline § 4.5.

---

## 1. Что делать (фазы 3–10)

### Phase 3 — Skills и Design Memory

**Точные факты, чтобы не тратить время на поиск:**

- `ai-stack/skills/` содержит **ровно 8** навыков: `beautiful-game-ui`,
  `browser-testing`, `frontend-development`, `mysql-database`, `php-legacy`,
  `python-engine`, `security-review`, `systematic-debugging`.
- `ai-stack/profiles/` — **4**: `frontend.yaml`, `backend-php.yaml`, `database.yaml`,
  `fullstack-game.yaml`.
- `ai-stack/design/` — **7**: `MASTER.md`, `COLORS.md`, `TYPOGRAPHY.md`,
  `COMPONENTS.md`, `LAYOUTS.md`, `ANIMATIONS.md`, `SCREEN_REFERENCE.md`.
- **Разрыв подтверждён:** 5 нужных сторонних навыков есть на диске, но **не подключены**:
  - `ui-ux-pro-max` → `C:\Users\grut\.codex\skills\ui-ux-pro-max\SKILL.md`
  - `frontend-design` → `C:\Users\grut\.codex\skills\frontend-design\SKILL.md`
  - `systematic-debugging`, `verification-before-completion`, `test-driven-development`
    → `C:\Users\grut\.codex\.tmp\plugins\plugins\superpowers\skills\<name>\SKILL.md`
    (**внимание: `.tmp` — временный каталог**)
- **Отсутствуют физически** (проверено glob по всему профилю):
  `web-design-guidelines`, `security-audit`, `php-modernization`.
- `ai-stack/design/screens/` **не существует**, хотя `SCREEN_REFERENCE.md` на него ссылается.

**Задача:** доказать не наличие файлов, а **фактическую передачу**: собрать prompt pack
для 4 профилей и показать, какие именно правила дизайна и навыки в него попали.

### Phase 4 — Repo Map

`hybrid/context/repo_map.py` — 396 строк. **В этой сессии не проверялся.**
Важно: `demo_project/` — **заглушка** (2 файла), для Phase 4 использовать `demo_php/`.
Тестовая задача из ТЗ: «Исправь обработчик экипировки предмета» — в `demo_php` действие
называется `use`, а не equip (см. `demo_php/ajax/inventory.php`).

### Phase 5 — Browser AI Bridge

Chrome + CDP **живой**: `http://127.0.0.1:9333`, Chrome 155.0.8059.39.
Актуальные DOM-факты ChatGPT — в `outbox/HANDOFF_BROWSER_AND_CODEX.md` § PROBLEM 2
(селекторы `#prompt-textarea`/`[data-message-author-role]`/`.markdown` **исчезли**;
рабочие якоря: `h4[data-conversation-role="assistant"]`,
`div[data-dil-message-id].DilResponseRoot`; `[data-talvt-turn-state]` — это обмен целиком,
а не ответ ассистента).

**Правило ТЗ:** не реализовывать автоматическое извлечение ответов из веб-чатов и обход
ограничений сервисов. Статус без реального вызова модели — `LOCAL WORKFLOW VERIFIED`,
**не** `LIVE VERIFIED`.

### Phase 6 — Игровая функция

**Инвентарь УЖЕ реализован** в `demo_php/` и **уже проверен в браузере** — эту часть
переделывать не нужно:

- `tests/test_demo_inventory.py` → **3 passed** на реальном PHP 8.5.11.
- `tools/visual_qa_inventory.py` → **16 PASS / 0 FAIL**: три viewport (1440×900,
  768×1024, 390×844) + 320 px, консоль пуста, переполнения нет, фильтры, empty state,
  экипировка сохраняется на сервере, `use` убывает ровно один раз, повторный
  `request_key` идемпотентен (`replayed: true`), негативные коды 400/404/409/409.
- Отчёт: `docs/VISUAL_QA_DEMO_INVENTORY.md`; скриншоты: `docs/visual-qa/`.

Файлы: `index.php` (CSRF в `<meta>`), `ajax/inventory.php` (4 предмета, действия
`list`/`use`/`equip`, `hash_equals`, идемпотентность по `request_key`, `flock`,
коды 400/401/404/409/500), `assets/inventory.js`, `assets/inventory.css`.

**Остаток Phase 6 (не сделан, не дублировать сделанное):**
- кросс-браузерная проверка (Firefox/Safari) — `NOT RUN`;
- сравнение скриншотов с baseline (визуальная регрессия) — `NOT RUN`;
- мобильные жесты (touch-swipe) — `NOT RUN`;
- живая проверка MySQL — `NOT RUN` (демо-инвентарь по замыслу на JSON-fixture).

**Критично:** реальная игра пользователя — `E:\OSPanel\domains\pokemonchic.com`.
Владелец подтвердил, что **работа ведётся именно для этого проекта**, но **не изменять
его** без отдельного разрешения. Отработка ведётся в `demo_php/`.

### Phase 7 — Local UI

`hybrid/local_ui/` — 4 модуля (`server.py`, `handlers.py`, `renderer.py`, `security.py`).
**В этой сессии не проверялся.** Проверить loopback bind, Host/Origin, защиту изменяющих
запросов, отсутствие произвольного доступа к локальным файлам.

### Phase 8 — Провайдеры

Фактическое состояние на 2026-10-09:

| Провайдер | Available | Причина |
|---|---|---|
| codex | да (резолвится) | но **BLOCKED** — см. § 2 ниже |
| groq | **нет** | `GROQ_API_KEY is not set` |
| openrouter | нет | `enabled: False` + нет ключа |
| deepseek_harness | нет | `disabled by configuration` |

`budget.allow_paid_api = False`. **Платных вызовов не делать.**

### Phase 9 — Subagents / Harness

Harness `enabled: False`. **Оставить отключённым**, пока локальный контракт не подтверждён
(это прямо требует ROADMAP, Этап 8, и ТЗ Phase 9).

### Phase 10 — Release acceptance

- `hybrid` **не в PATH**: `Get-Command hybrid` → ничего, хотя `pyproject.toml` объявляет
  `[project.scripts] hybrid = "hybrid.cli:main"`. Пакет не установлен как console script
  в `.venv`. Нужен `pip install -e .` в чистом venv.
- `pytest-timeout` **не установлен** — флаг `--timeout` не работает.
- Playwright (Python) **отсутствует** в venv; Visual QA опирается на `agent-browser` 0.38.2.
- Не включать `.env`, `.hybrid`, browser profiles и локальные секреты в релиз.
- Рабочее дерево содержит **38 незакоммиченных файлов** — сформировать reviewable diff,
  решение о коммите за владельцем.

---

## 2. BLOCKER, который может решить именно Codex

**Codex CLI не может писать файлы.** Это P0 задания и **не** дефект Python-движка.

**Симптом:** `codex exec` доходит до модели, тратит токены, файл не создаётся.
`codex doctor` → `✗ sandbox / provisioning failed / error code helper_unknown_error`.

**Точная причина** (`C:\Users\grut\.codex\.sandbox\sandbox.2026-10-09.log`):

```
runtime read/execute validation failed: validate runtime read/execute access on
...\runtimes\cua_node\3dd31cfff853001c\bin\node_repl.exe:
open ACL target for root-only update: Процесс не может получить доступ к файлу,
так как этот файл занят другим процессом. (os error 32)
```

`codex-windows-sandbox-setup.exe` не может выдать ACL на runtime-бинарник
`node_repl.exe` → весь `setup refresh` помечается ошибочным → ломаются **все три** пути
записи: shell, собственный patch writer Codex, автономный `codex sandbox`.

**Уже исключено измерениями:**

| Гипотеза | Результат |
|---|---|
| 13 процессов `node_repl.exe` держат файл | остановлены — ошибка сохранилась |
| MCP-сервер `node_repl` из `config.toml` | отключён флагом — ошибка сохранилась |
| Нет прав / не-admin | DAC пишется, `IsAdmin=True` — не причина |
| Режим sandbox (`restricted`/`offline`/`online`/`elevated`/`none`) | все не помогают |

**Вероятный фактор:** смешение установок.
- `C:\Users\grut\.codex\.sandbox-bin\codex.exe` — 317.9 МБ
- `C:\Users\grut\AppData\Local\OpenAI\Codex\bin\9691020b546a15b2\codex.exe` — 317.9 МБ
  (**только здесь** есть `codex-windows-sandbox-setup.exe`)
- Store-пакет `OpenAI.Codex` 26.1002.7124.0
- В логе: `helper executable resolution: route=materialized
  source=...AppData...\codex.exe selected=C:\Users\grut\.codex\.sandbox-bin\codex.exe`,
  то есть helper материализуется в `.sandbox-bin\`, где setup-бинарника **нет**.

**Поддерживаемое восстановление (обязательное ограничение):**
переустановить/обновить Codex CLI из одобренного дистрибутива так, чтобы `codex.exe`,
`codex-windows-sandbox-setup.exe` и `runtimes\cua_node\...` происходили из **одной**
установки, и пересоздать sandbox-состояние
(`~\.codex\.sandbox\{setup_marker.json, setup_error.json, cap_sid}`).

**ЗАПРЕЩЕНО Проектом:** `--dangerously-bypass-approvals-and-sandbox` нельзя использовать
как исправление (hard rule №1 PROJECT_CONTEXT). Не отключать sandbox и approval.

**Приёмочный тест Phase 2 (когда среда починена):** в отдельном временном репозитории
поручить Codex изменить небольшой PHP-файл; проверить, что файл изменён в разрешённом
окружении, патч сформирован, исходный проект не изменён, `apply` требует подтверждения.

**Если починить нельзя** — честно оставить `BLOCKED` и продолжить независимые фазы
(3, 4, 7, 10 не требуют Codex CLI).

---

## 3. Ограничения работы

1. **Не коммитить** и не применять изменения к основному проекту без разрешения владельца.
2. **Не изменять** `E:\OSPanel\domains\pokemonchic.com` (реальная игра) без разрешения.
3. **Не делать платных вызовов** — `allow_paid_api=False`, ключей Groq/OpenRouter нет.
4. **Не отправлять** `.env`, cookies, ключи и приватные данные провайдерам.
5. **Не отключать** sandbox/approval как способ обойти ошибку.
6. **Не помечать** Visual QA как PASS без реального браузерного прогона и скриншотов.
7. **Не называть** mock-проверку реальным запуском модели. Без живого вызова — только
   `LOCAL WORKFLOW VERIFIED`.
8. Непроведённые проверки помечать `NOT RUN`, недоступные — `BLOCKED`/`NOT VERIFIED`.

**Полезно:** не переписывать работающие подсистемы. Негативные сценарии уже доказаны
16 прогонами — опираться на них, а не выдумывать заново.
