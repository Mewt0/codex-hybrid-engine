# CONFORMITY BASELINE — Phase 0

**Задание:** CODEX HYBRID ENGINE — MASTER CONFORMITY FIX, Phase 0.
**Дата снятия baseline:** 2026-10-09.
**Метод:** все цифры ниже получены новым прогоном в этой сессии, а не скопированы из ROADMAP.
Расхождения с прежними заявлениями отмечены явно.

---

## 1. Точная исходная точка

| Параметр | Значение |
|---|---|
| Репозиторий | `F:\codex-hybrid-engine` |
| Git commit | `fe1f37e17e3a229ff18f5090a5c44ac0344fabe3` |
| Дата коммита | 2026-10-09 00:53:54 +0200 |
| Тема | `perf(bridge): turn ChatGPT automation into a fast, provable state machine` |
| Ветка | `master` |
| Рабочее дерево | **38 изменённых/неотслеживаемых файлов — НЕ чистое** |
| Python (venv) | 3.12.10 (`.venv\Scripts\python.exe`) |
| Python (global) | 3.12.10 |
| Node | v24.19.0 |
| Git | 2.55.0.windows.3 |
| ОС | Windows 11 IoT EnterpriseS, 10.0.26100, ru-RU |

**Важно:** `F:\work` (рабочая директория сессии) пуста. Проект физически лежит в
`F:\codex-hybrid-engine`. Все команды ниже выполнялись там.

### 1.1. Состояние рабочего дерева

`git status --porcelain` → **38 записей**. Полный состав:

**Удалены из индекса (staged deletion):** `.chatgpt-prompt-1.md`, `.session-check.png`

**Изменены (unmodified-в-индексе, изменены в рабочем дереве):**
`.gitignore`, `README.md`, `demo_php/ajax/inventory.php`, `demo_php/assets/inventory.css`,
`demo_php/assets/inventory.js`, `demo_php/index.php`, `docs/BROWSER_BRIDGE.md`,
`hybrid/browser_bridge/browser_state.py`, `hybrid/browser_bridge/chatgpt_ui.py`,
`hybrid/browser_bridge/webchat.py`, `hybrid/cli.py`, `hybrid/config.py`,
`hybrid/context/__init__.py`, `hybrid/context/repo_map.py`, `hybrid/providers/codex.py`,
`tests/test_harness_adapter.py`, `tests/test_qa3_regressions.py`, `tests/test_repo_map.py`,
`tests/test_webchat_automation.py`, `tools/inspect_live_dom.py`, `tools/smoke_browser_state.py`

**Неотслеживаемые (untracked):**
`docs/ROADMAP_FULL.md`, `error.log`, `hybrid/browser_bridge/sites/`,
`hybrid/context/selection.py`, `hybrid/integrations/codex_cli_delegate.py`,
`outbox/HANDOFF_BROWSER_AND_CODEX.md`, `outbox/HANDOFF_BROWSER_CHAT.md`,
`outbox/TZ_DEEPSEEK_BROWSER.md`, `tests/test_deepseek_profile.py`,
`tests/test_demo_inventory.py`, `tests/test_site_profiles.py`

**Вывод:** состояние соответствует предупреждению ROADMAP (§ «Примечание о снимке
рабочего дерева») и правилу PROJECT_CONTEXT «не включать чужую незакоммиченную работу
в релизную оценку». Изменения применяет и коммитит человек. Ничего не удалено и не
закоммичено этой сессией.

---

## 2. Версии окружения

| Инструмент | Состояние | Путь / версия |
|---|---|---|
| Python | OK | 3.12.10 |
| Git | OK | `C:\Program Files\Git\cmd\git.EXE`, 2.55.0.windows.3 |
| Node | OK | `C:\Program Files\nodejs\node.EXE`, v24.19.0 |
| **PHP** | **не в PATH, но доступен** | `E:\OSPanel\modules\php\PHP_8.5.11\php.exe` |
| MySQL / MariaDB | есть на диске | `E:\OSPanel\modules\database\MariaDB-10.x\bin\mysql.exe` |
| Chrome + CDP | **живой** | Chrome 155.0.8059.39, DevTools на `http://127.0.0.1:9333` |
| agent-browser | OK (глобально) | `C:\Users\grut\AppData\Roaming\npm\agent-browser` (0.38.2) |
| **Playwright (Python)** | **ОТСУТСТВУЕТ в venv** | `importlib.util.find_spec('playwright')` → `False` |
| PyYAML | OK | 6.0.3 |
| pytest | OK | 9.1.1 |
| **Codex CLI** | **установлен в 2 копиях, не в PATH** | 0.162.0-alpha.2 |
| Codex Store-пакет | установлен | `OpenAI.Codex` 26.1002.7124.0 |

### 2.1. Важное расхождение с ROADMAP

ROADMAP и handoff утверждают «**PHP: NOT FOUND**». Это **неверно как факт о машине**:
PHP 8.5.11 установлен в OSPanel, и `hybrid doctor` его не видит только потому, что
`hybrid/cli.py` проверяет `shutil.which("php")` без OSPanel-фолбэка, тогда как
`hybrid/quality/checks.py::php_binary()` этот фолбэк **имеет** и PHP находит:

```
php_binary(): E:\OSPanel\modules\php\PHP_8.5.11\php.exe
> php -l demo_php/index.php
No syntax errors detected in demo_php/index.php
```

То есть PHP-проверки качества фактически работают, а `doctor` их недооценивает.
Это расхождение диагностики, а не отсутствие инструмента.

---

## 3. Тесты

### 3.1. Полный прогон

```
.venv\Scripts\python.exe -m pytest -q
........................................................................ [ 31%]
........................................................................ [ 63%]
........................................................................ [ 95%]
...........                                                              [100%]
227 passed in 118.37s (0:01:58)
```

| Метрика | Значение |
|---|---|
| PASS | **227** |
| FAIL | 0 |
| SKIP | 0 (в сводке `-q` не показано) |
| ERROR | 0 |
| Время | 118.37 с |

**Расхождение с ROADMAP:** документ заявляет `224 passed`. Новый прогон даёт
`227 passed`. Разница объяснима неотслеживаемыми тестовыми файлами
(`tests/test_deepseek_profile.py`, `tests/test_demo_inventory.py`,
`tests/test_site_profiles.py`), которых на момент снятия ROADMAP в прогоне не было.
**Цифру 224 считать устаревшей.**

Примечание: `pytest-timeout` не установлен, поэтому `--timeout` не поддерживается —
первая попытка прогона с этим флагом завершилась ошибкой аргументов.

### 3.2. Тесты по файлам (17 файлов + conftest)

| Файл | Строк | Покрытие |
|---|---:|---|
| `tests/test_webchat_automation.py` | 980 | CDP/state machine ChatGPT |
| `tests/test_browser_bridge.py` | 267 | включая 7 регрессий QA5 |
| `tests/test_harness_adapter.py` | 253 | контракт Harness |
| `tests/test_engine.py` | 190 | жизненный цикл движка |
| `tests/test_qa3_regressions.py` | 170 | регрессии QA3 |
| `tests/test_repo_map.py` | 148 | карта репозитория |
| `tests/test_local_ui.py` | 147 | local UI и безопасность |
| `tests/test_report.py` | 120 | полнота отчёта, `NOT RUN` |
| `tests/test_security_regressions.py` | 111 | path/prompt safety |
| `tests/test_cdp_websocket.py` | 107 | протокол CDP |
| `tests/test_demo_inventory.py` | 92 | PHP-инвентарь (3 теста, реальный PHP) |
| `tests/test_visual_qa.py` | 88 | Visual QA orchestration |
| `tests/test_qa4_regressions.py` | 83 | регрессии QA4 |
| `tests/test_context_skills.py` | 47 | контекст и профили |
| `tests/test_site_profiles.py` | 36 | SiteProfile |
| `tests/test_deepseek_profile.py` | 32 | DeepSeek fail-closed |

Проверено отдельно: `pytest tests/test_demo_inventory.py -q` → **3 passed** на
реальном PHP 8.5.11 (не SKIP).

---

## 4. Фактически существующие компоненты

### 4.1. Python-пакет `hybrid/`

51 `.py`-файл, **9587 строк**. Крупнейшие: `browser_bridge/browser_state.py` (1031),
`cli.py` (1218), `browser_bridge/webchat.py` (780), `browser_bridge/sites/chatgpt.py` (482),
`visual/driver.py` (410), `context/repo_map.py` (396), `browser_bridge/cdp.py` (381),
`controller.py` (338), `context/__init__.py` (333),
`integrations/codex_cli_delegate.py` (306), `context/selection.py` (288).

Все заявленные подсистемы **физически существуют**:
`context/{repo_map,prompt_pack,selection,file_context}.py`,
`quality/checks.py`, `execution/worktree.py`,
`local_ui/{server,handlers,renderer,security}.py`,
`visual/{driver,engine}.py`, `browser_bridge/*` (19 файлов),
`providers/{base,codex,groq,mock,openrouter}.py`.

### 4.2. `ai-stack/` — Unified Skills и Design Memory

| Компонент | Состояние |
|---|---|
| `ai-stack/PROJECT_CONTEXT.md` | существует, 41 строка, 6 Hard rules |
| `ai-stack/profiles/` | **4 профиля**: `frontend.yaml`, `backend-php.yaml`, `database.yaml`, `fullstack-game.yaml` |
| `ai-stack/skills/` | **8 навыков**, у каждого ровно один `SKILL.md` |
| `ai-stack/design/` | **7 файлов**: `MASTER.md`, `COLORS.md`, `TYPOGRAPHY.md`, `COMPONENTS.md`, `LAYOUTS.md`, `ANIMATIONS.md`, `SCREEN_REFERENCE.md` |
| `ai-stack/design/screens/` | **NOT FOUND** — на него ссылается `SCREEN_REFERENCE.md`; битая ссылка |

Навыки: `beautiful-game-ui`, `browser-testing`, `frontend-development`,
`mysql-database`, `php-legacy`, `python-engine`, `security-review`,
`systematic-debugging`.

### 4.3. Сторонние навыки (проверка по диску)

Полный glob `**/SKILL.md` под `C:\Users\grut` → **758 путей**.

| Навык из ТЗ | Статус | Путь |
|---|---|---|
| UI/UX Pro Max | **НАЙДЕН** | `C:\Users\grut\.codex\skills\ui-ux-pro-max\SKILL.md` (и дубль в `.dsh\skills\`) |
| Frontend Design | **НАЙДЕН** | `C:\Users\grut\.codex\skills\frontend-design\SKILL.md` |
| Playwright | иного имени нет; есть `playwright-cli`, `playwright-component-testing`, `playwright-trace` в `playwright-core\lib\tools\skills\` | — |
| Web Design Guidelines | **NOT FOUND** | — |
| Security Audit | **NOT FOUND** | — |
| PHP Modernization | **NOT FOUND** | — |
| Systematic Debugging | **НАЙДЕН** | `C:\Users\grut\.codex\.tmp\plugins\plugins\superpowers\skills\systematic-debugging\SKILL.md` |
| Verification Before Completion | **НАЙДЕН** | `...\.tmp\plugins\plugins\superpowers\skills\verification-before-completion\SKILL.md` |
| Test Driven Development | **НАЙДЕН** | `...\.tmp\plugins\plugins\superpowers\skills\test-driven-development\SKILL.md` |

**Критично:** найденные пять навыков лежат **вне** `ai-stack/skills/` — в
`C:\Users\grut\.codex\skills\` и в **временном** каталоге `.codex\.tmp\plugins\`.
Движок читает только `ai-stack/skills/`, поэтому эти навыки **не попадают** в
prompt pack. Разрыв между «навык есть на диске» и «навык используется» подтверждён.

### 4.4. Демонстрационные проекты

| Путь | Состав | Оценка |
|---|---|---|
| `demo_project/` | `app.js` (51 б), `package.json` (19 б) | **заглушка**, не приложение |
| `demo_php/` | `index.php`, `ajax/inventory.php`, `assets/inventory.js`, `assets/inventory.css` | **полноценный инвентарь** |

**Инвентарь в `demo_php` уже реализован** (вопреки ожиданию ТЗ «S сделать демонстрацию»):
CSRF через `hash_equals`, идемпотентность по `request_key`, состояние под `flock`,
фильтры `rarity`/`q`, коды 400/401/404/409/500, 4 предмета. Покрыт
`tests/test_demo_inventory.py` (3 теста, реальный PHP).

### 4.5. Что такое «QA5» (уточнение терминологии)

Наивная трактовка «QA5 = отдельный набор проверок в `quality/checks.py`» **неверна**.
`quality/checks.py` содержит только `validate_paths`, `php_binary`, `run_quality`,
`validate_dependencies`; имён QA1..QA5 там нет.

**QA5 — это пятый раунд независимого ревью Browser AI Bridge.** Строка `QA5`
встречается в 2 файлах: `PROJECT_CONFORMITY_AUDIT.md:187` и
`outbox/chatgpt/README.md:34`. Документ ревью — `docs/QA_ROUND_5.md` (58 строк),
три замечания: (1) пути патча собирались только с новой стороны, из-за чего удаление
защищённого пути проходило проверку; (2) проверка защищённых путей была
регистрозависимой; (3) хэш считался до нормализации CRLF.

Слово `QA5` в тестах отсутствует, но все 7 тестов, перечисленных в `QA_ROUND_5.md`,
реально есть в `tests/test_browser_bridge.py` (строки 217, 229, 238, 247, 255, 269, 277).
Файла `test_qa5_regressions.py` нет.

Поэтому Phase 1 задачи («проверить QA5: `.hybrid/`, ignored dirs, корректный apply»)
трактована как проверка **трёх названных рисков**, а не как поиск файла тестов.

---

## 5. Обнаруженные блокеры

### BLOCKER-1 (P0) — Codex CLI не может писать файлы. `helper_unknown_error`

| Параметр | Значение |
|---|---|
| Статус | **BLOCKED — внешняя причина, подтверждено воспроизведением** |
| Симптом | `codex exec` доходит до модели, тратит токены, но не создаёт файл |
| Код ошибки | `helper_unknown_error: setup refresh had errors` |

**Точная причина (из `C:\Users\grut\.codex\.sandbox\sandbox.2026-10-09.log`):**

```
runtime read/execute validation failed: validate runtime read/execute access on
C:\Users\grut\AppData\Local\OpenAI\Codex\runtimes\cua_node\3dd31cfff853001c\bin\node_repl.exe:
open ACL target for root-only update: Процесс не может получить доступ к файлу,
так как этот файл занят другим процессом. (os error 32)
```

`codex-windows-sandbox-setup.exe` пытается выдать ACL на runtime-бинарник
`node_repl.exe`, получает **sharing violation (os error 32)** и помечает весь
`setup refresh` как ошибочный. Следствие: `codex exec` не может запустить ни shell
(`Failed to create unified exec process`), ни даже собственный patch writer
(`Failed to write file ...\hello.txt`). То есть сломаны **все три** способа записи.

**Что исключено измерениями (не догадками):**

| Гипотеза | Проверка | Результат |
|---|---|---|
| 13 процессов `node_repl.exe` держат файл | остановлены все 13, повторный живой прогон | ошибка **сохранилась** |
| MCP-сервер `node_repl` из `config.toml` | прогон с `-c mcp_servers.node_repl.enabled=false` | ошибка **сохранилась** |
| Нехватка прав / не-admin | DAC на файл записывается, `IsAdmin=True`, файл открывается | **не причина** |
| Режим sandbox | `restricted`, `offline`, `online`, `elevated`, `none` | **все не помогают** |
| Смешение установок Codex | две копии `codex.exe` (317.9 МБ каждая) + Store-пакет `26.1002.7124.0` | вероятный фактор |

**Дополнительный факт:** `codex-windows-sandbox-setup.exe` существует **только** в
`...\AppData\Local\OpenAI\Codex\bin\9691020b546a15b2\`, тогда как
`~\.codex\.sandbox-bin\` (куда механизм сам материализует helper: в логе
`route=materialized ... selected=C:\Users\grut\.codex\.sandbox-bin\codex.exe`)
содержит **только `codex.exe`** и **не содержит** setup-бинарника. Это согласуется с
формулировкой handoff «`codex-windows-sandbox-setup.exe` is missing», но точная
причина — именно незавершённая ACL-операция над `node_repl.exe`, а не отсутствие файла.

**Направление восстановления (поддерживаемое, без обхода sandbox):**
переустановить/обновить Codex CLI из одобренного дистрибутива так, чтобы
`codex.exe`, `codex-windows-sandbox-setup.exe` и `runtimes\cua_node\...` происходили
из **одной** установки, и пересоздать sandbox-состояние
(`%USERPROFILE%\.codex\.sandbox\{setup_marker.json, setup_error.json, cap_sid}`).
Правило PROJECT_CONTEXT «Never disable sandbox or approval mechanisms» соблюдено:
`--dangerously-bypass-approvals-and-sandbox` **не применялся как решение**.

**Честная формулировка:** исправление находится **вне кода Hybrid Engine**.
Движок уже передаёт `--sandbox workspace-write` и корректное окружение
(`CodexProvider.ENV_ALLOWED`); он не может починить ACL-операцию чужого helper-процесса.

### BLOCKER-2 (P2) — `hybrid doctor` недооценивает PHP

`doctor` печатает `PHP: NOT FOUND`, хотя PHP 8.5.11 доступен и `checks.php_binary()`
его находит. Диагностика занижает готовность. Исправление — в `hybrid/cli.py`
(использовать `php_binary()` вместо `shutil.which`).

### BLOCKER-3 (P2) — entry point `hybrid` не в PATH

`Get-Command hybrid` → ничего. CLI работает только как `python -m hybrid.cli`.
При этом `pyproject.toml` объявляет `[project.scripts] hybrid = "hybrid.cli:main"`,
то есть пакет в `.venv` установлен не как консольный скрипт.

### BLOCKER-4 (P1) — Playwright отсутствует

`importlib.util.find_spec('playwright')` в venv → `False`. Visual QA в браузере
опирается на внешний `agent-browser` (установлен глобально, 0.38.2), а не на
Python Playwright. Это ограничивает Phase 6 (Visual QA).

### BLOCKER-5 (P1) — разрыв между наличием навыков и их использованием

5 из 9 требуемых сторонних навыков есть на диске, но ни один не подключён в
`ai-stack/skills/`. Движок их не видит. Три навыка (`web-design-guidelines`,
`security-audit`, `php-modernization`) отсутствуют физически. См. § 4.3.

### BLOCKER-6 (P3) — битая ссылка `ai-stack/design/screens/`

`SCREEN_REFERENCE.md` ссылается на каталог скриншотов, которого нет.

---

## 6. Критерий завершения Phase 0

> «Исходное состояние можно воспроизвести без потери пользовательских изменений.»

| Требование | Статус |
|---|---|
| Точный Git commit зафиксирован | **PASS** — `fe1f37e` |
| Состояние рабочего дерева описано | **PASS** — 38 файлов перечислены, ничего не изменено и не удалено |
| PASS / FAIL / SKIP тестов | **PASS** — 227 / 0 / 0 |
| Версии окружения | **PASS** — § 2 |
| Список фактически существующих компонентов | **PASS** — § 4 |
| Обнаруженные блокеры | **PASS** — 6 блокеров с доказательствами |
| Пользовательские изменения не потеряны | **PASS** — коммитов и удалений не выполнялось |

**Phase 0: COMPLETE.**

---

## 7. Артефакты этой фазы

| Файл | Назначение |
|---|---|
| `docs/CONFORMITY_BASELINE.md` | этот документ |
| `tools/conformity_e2e.py` | исполняемый E2E-прогон Phase 1.1/1.2/1.4 |
| `docs/conformity_e2e_result.json` | машинное доказательство прогона |
| `tools/conformity_git_safety.py` | исполняемые Git-регрессии Phase 1.3 |
| `docs/conformity_git_safety_result.json` | машинное доказательство прогона |
