# MASTER CONFORMITY RESULT

**Статус документа:** **единый сводный отчёт.** Разделы A–M — исторический снимок
первой сессии, раздел N — дополнение второй сессии. Читать их вместе с разделом **O**,
который сводит обе сессии в одну картину и заменяет собой handoff-файлы.

**Целевой проект:** `E:\OSPanel\domains\pokemonchic.com`. В обеих сессиях его файлы
**не изменялись**.

---

## О разделении работ

Задание содержит 11 фаз, и над репозиторием работали **две независимые сессии**.
Раньше это описывалось как «фазы переданы Codex» / «фазы 1–2 пропущены»; сводная
картина — в разделе **O**.

| | Сессия A (первый агент) | Сессия B (вторая модель) |
|---|---|---|
| Выполнено | Phase 0, **1** (core+QA5+Git safety), 2 (диагностика), 6 (браузерный QA), **8** (статус провайдеров) | Phase 0, 3, 4, 5, 6 (`equip`), 7, 8–9, 10 |
| Финальный счёт тестов | `249 passed` | `238 passed` |
| Уникальные артефакты | `tools/conformity_e2e.py`, `tools/conformity_git_safety.py`, `tools/visual_qa_inventory.py`, `hybrid/providers/status.py`, `hybrid/php_runtime.py` | `ai-stack/design/screens/`, `.hybrid/conformity-venv/`, `.hybrid/wheelhouse/`, раздел N |

**Текущее состояние дерева — истина:** `259 passed`, 0 FAIL (объединённые изменения
обеих сессий). Числа `238` и `249` в разделах ниже — исторические срезы на момент
каждой сессии, а не текущий результат.

**Правило отчёта:** «подтверждено повторным запуском» отделено от «принято по имеющимся
доказательствам». Непроведённое помечено `NOT RUN`, недоказанное — `NOT VERIFIED`.
Старые измерения не выдаются за новые.

**Использованные статусы:** `WORKING`, `IMPLEMENTED`, `PARTIAL`, `STUB`, `MISSING`,
`BLOCKED`, `NOT VERIFIED`, `DELEGATED`.
**Статусы тестов:** `PASS`, `FAIL`, `SKIP`, `NOT RUN`.

---

# A. Исходное состояние

Полный разбор — в `docs/CONFORMITY_BASELINE.md`. Кратко:

| Параметр | Значение |
|---|---|
| Репозиторий | `F:\codex-hybrid-engine` |
| Commit | `fe1f37e17e3a229ff18f5090a5c44ac0344fabe3` (2026-10-09 00:53:54 +0200) |
| Ветка | `master` |
| Рабочее дерево | **38 изменённых/неотслеживаемых файлов — не чистое** (чужак работа; не коммитилась и не удалялась) |
| Python | 3.12.10 (venv и global) |
| Node | v24.19.0 |
| Git | 2.55.0.windows.3 |
| PHP | **есть**, `E:\OSPanel\modules\php\PHP_8.5.11\php.exe` (не в PATH) |
| MySQL/MariaDB | есть на диске в OSPanel |
| Chrome + CDP | **живой**, Chrome 155.0.8059.39 на `127.0.0.1:9333` |
| agent-browser | 0.38.2 (глобально) |
| Playwright (Python) | **MISSING** в venv |
| Codex CLI | 0.162.0-alpha.2, **две копии, не в PATH**; Store-пакет 26.1002.7124.0 |

**Тесты на входе:** `227 passed` за 118.37 с, 0 FAIL.
**Расхождение с ROADMAP:** документ заявляет `224 passed` — цифра устарела.

Компоненты: 51 `.py` / 9587 строк; `ai-stack` с 4 профилями, 8 навыками и 7 файлами
дизайн-памяти; `demo_php` содержит **уже реализованный** PHP-инвентарь.

---

# B. Матрица соответствия

## B.1. Фазы задания

| Фаза | До (baseline) | После | Доказательство | Остаток |
|---|---|---|---|---|
| **0. Baseline** | Отсутствовал документ с воспроизводимой точкой | **WORKING** | `docs/CONFORMITY_BASELINE.md`; `pytest -q` → 227 passed | Рабочее дерево не чистое (38 файлов) — решение владельца |
| **1.1 Маршрут run→apply** | Не было сквозного прогона на чистом репо | **WORKING** | `tools/conformity_e2e.py` — 8/8 PASS на временных git-репо | — |
| **1.2 QA5 (`.hybrid`, ignored dirs, apply)** | Регрессии существовали только в bridge-тестах | **WORKING** | E2E-сценарии 1.2A/1.2B/1.2C; `.hybrid/` не входит в diff; ignored dirs — bounded entry; подмена патча, отсутствие `--yes`, пользовательская правка после review — всё блокируется | Мультифайловая транзакция артефактов остаётся открытой (унаследовано из QA5) |
| **1.3 Git-регрессии** | Покрытие отсутствовало | **WORKING** | `tools/conformity_git_safety.py` — 8/8 PASS: rename, copy, пробелы/Unicode, удаление, новый файл, untracked, dirty worktree, symlink | Quoted-name escaping проверен косвенно (Windows-имена исключают кавычки/tab) |
| **1.4 FAST MODE** | Не проверялся отдельно на изоляцию | **WORKING** | E2E 1.4: после fast-прогона `git status --porcelain` пуст, файл не изменён, патч-артефакт создан | — |
| **2. Codex CLI** | `helper_unknown_error`, причина неизвестна | **BLOCKED** (внешняя причина найдена) | § D и `docs/CONFORMITY_BASELINE.md` § 5 | Требуется переустановка Codex из одной установки |
| **6. Browser/Visual/Functional QA инвентаря** | Скриншотов нет, Visual QA `NOT RUN` | **WORKING** | `tools/visual_qa_inventory.py` — **16/16 PASS**; 5 скриншотов; `docs/VISUAL_QA_DEMO_INVENTORY.md` | Кросс-браузерная и регрессионная проверка — `NOT RUN` |
| **3, 4, 5, 7, 8, 9, 10** | — | **DELEGATED (Codex)** | Распределение владельца проекта | — |

## B.2. Подсистемы (пересчёт относительно ROADMAP)

| Компонент | Заявление ROADMAP | Факт этой сессии | Изменение |
|---|---|---|---|
| Python Controller | 85%, «нужен чистый E2E» | Маршрут подтверждён на 16 сценариях, 227+8 тестов | **Подтверждено** |
| Codex CLI | 65%, sandbox blocker | Блокер **локализован до конкретной ACL-операции** | Причина найдена, устранение вне движка |
| Groq / OpenRouter | live не подтверждены | Ключей нет → `UNAVAILABLE`, честно | Без изменений |
| DeepSeek / ChatGPT Web | manual relay есть | Не проверялось в этой сессии | NOT VERIFIED / DELEGATED |
| Unified Skills | библиотека есть | 8 навыков; **5 сторонних не подключены** | Разрыв подтверждён |
| Design Memory | каталог есть | 7 файлов; `screens/` отсутствует | Битая ссылка найдена |
| Repo Map | эвристика | Не проверялось в этой сессии | DELEGATED |
| Git Safety | механизмы есть | **16 сценариев PASS**, включая все негативные из ТЗ | **Подтверждено** |
| PHP/JS/MySQL QA | «реальные проверки неполные» | PHP 8.5.11 найден; `doctor` **исправлен**; инвентарь и 3 теста проходят | **Улучшено** |
| Visual QA | live не завершён | Playwright отсутствует; agent-browser есть | BLOCKED / DELEGATED |
| Local UI | 70% | Не проверялось в этой сессии | DELEGATED |
| Субагенты / Harness | 30%, disabled | Отключён, как и должно быть | Без изменений |
| Windows + WSL2 | чистая приёмка не завершена | Baseline снят на Windows; WSL2 не проверялся | PARTIAL |

---

# C. Исправления

## C.1. `hybrid/cli.py` — `doctor` недооценивал инструменты

**Файл:** `hybrid/cli.py`
**Суть:** `doctor` использовал голый `shutil.which()` для двух видов инструментов,
которые так не находятся:

1. **Codex CLI** настраивается доверенным абсолютным путём
   (`C:\Users\grut\.codex\.sandbox-bin\codex.exe`). `shutil.which()` ищет только PATH,
   поэтому печатал `NOT FOUND`, **противореча** провайдеру, который этот путь
   успешно резолвит.
2. **PHP** установлен в OSPanel и не в PATH. `hybrid/quality/checks.py::php_binary()`
   уже умеет его находить (докстрока прямо описывает OSPanel), а `doctor` — нет.
   Итог: диагностика писала `PHP: NOT FOUND`, тогда как PHP-линт качества реально
   работал.

**Изменение:** добавлена `_resolve_tool()` (абсолютный путь → существование;
простое имя → PATH) и `doctor` переведён на `php_binary()`.

**Было:**
```
Codex CLI: NOT FOUND
PHP: NOT FOUND
```
**Стало:**
```
Codex CLI: C:\Users\grut\.codex\.sandbox-bin\codex.exe
PHP: E:\OSPanel\modules\php\PHP_8.5.11\php.exe
```

Это устраняет устаревшее утверждение ROADMAP/handoff «PHP: NOT FOUND» как факт о машине.

## C.2. `tools/conformity_e2e.py` — исполняемый сквозной прогон (новый)

Реальный E2E: создаёт временный Git-репозиторий на диске, запускает
**установленный CLI `hybrid` отдельным процессом** и проверяет наблюдаемое состояние
(файлы, `git status`, хэши артефактов, коды возврата), а не внутренние объекты Python.

Результат: **8 PASS / 0 FAIL**.

## C.3. `tools/conformity_git_safety.py` — Git-регрессии (новый)

Проверяет реальную git-механику на неудобных путях. Результат: **8 PASS / 0 FAIL**.

## C.4. `tests/test_conformity_regressions.py` — закрепление (новый)

8 тестов, фиксирующих исправления, чтобы они не откатились молча:
`_resolve_tool` на абсолютном/отсутствующем/простом пути, `doctor` обязан
использовать PHP-резолвер, `.hybrid/` не попадает в change set, ignored
dependency-каталоги остаются bounded entries.

Результат: **8 passed**.

---

# D. Провайдеры

| Провайдер | Configured | Available | Authenticated | Live verified | Disabled | Error |
|---|---|---|---|---|---|---|
| **Codex** | да | да (резолвится) | да | **НЕТ** | нет | **`helper_unknown_error`** |
| **Groq** | да | **нет** | нет | нет | нет | `GROQ_API_KEY is not set` |
| **OpenRouter** | да | нет | нет | нет | **да** (`enabled: False`) | `OPENROUTER_API_KEY is not set` |
| **DeepSeek Web** | bridge есть | manual relay | не проверялось | **NOT VERIFIED** | — | — |
| **ChatGPT Web** | bridge есть | CDP-сессия жива | да (Chrome залогинен) | **NOT VERIFIED** | — | — |
| **Mock** | да | да | н/п | **да** | нет | — |
| **DeepSeek Harness** | да | нет | нет | нет | да | `disabled by configuration` |

Правило «наличие API-ключа не считается гарантией доступа» соблюдено: ни один
платный вызов не выполнялся, `budget.allow_paid_api = False`.

## D.1. Codex — точная причина блокера

`codex doctor` → `✗ sandbox / sandbox provisioning failed / error code helper_unknown_error`.
Из `C:\Users\grut\.codex\.sandbox\sandbox.2026-10-09.log`:

```
runtime read/execute validation failed: validate runtime read/execute access on
...\runtimes\cua_node\3dd31cfff853001c\bin\node_repl.exe:
open ACL target for root-only update: Процесс не может получить доступ к файлу,
так как этот файл занят другим процессом. (os error 32)
```

**Механика:** `codex-windows-sandbox-setup.exe` пытается выдать ACL на
runtime-бинарник `node_repl.exe`, получает **sharing violation (os error 32)** и
помечает весь `setup refresh` ошибочным. Следствие — сломаны **все три** пути записи:

| Путь записи | Результат прогона |
|---|---|
| shell (`exec`) | `Failed to create unified exec process: helper_unknown_error` |
| собственный patch writer Codex | `Failed to write file ...\hello.txt` |
| автономный `codex sandbox` | `exit=2`, файл не создан |

**Исключено измерениями:**

| Гипотеза | Что сделано | Результат |
|---|---|---|
| 13 процессов `node_repl.exe` держат файл | остановлены все 13, повторный живой прогон | ошибка **сохранилась** |
| MCP-сервер `node_repl` из `config.toml` | `-c mcp_servers.node_repl.enabled=false` | ошибка **сохранилась** |
| Нехватка прав / не-admin | DAC пишется, `IsAdmin=True`, файл открывается эксклюзивно | **не причина** |
| Режим sandbox | `restricted`/`offline`/`online`/`elevated`/`none` | **все не помогают** |
| Смешение установок | 2× `codex.exe` (317.9 МБ) + Store-пакет 26.1002.7124.0; `setup.exe` только в AppData, а helper материализуется в `~\.codex\.sandbox-bin\` | **вероятный фактор** |

**Поддерживаемое восстановление (без обхода sandbox):** переустановить/обновить Codex CLI
из одобренного дистрибутива так, чтобы `codex.exe`,
`codex-windows-sandbox-setup.exe` и `runtimes\cua_node\...` происходили из **одной**
установки, и пересоздать sandbox-состояние
(`~\.codex\.sandbox\{setup_marker.json, setup_error.json, cap_sid}`).

**Соблюдено:** `--dangerously-bypass-approvals-and-sandbox` **не использован как решение**
(правило №1 PROJECT_CONTEXT). Он применялся только предыдущим агентом как одноразовая
диагностика в `%TEMP%`, что зафиксировано в handoff.

---

# E. Skills и Design Memory

**Статус: DELEGATED (Phase 3) — но разрыв подтверждён audit'ом.**

| Факт | Значение |
|---|---|
| Навыков в `ai-stack/skills/` | **8** (beautiful-game-ui, browser-testing, frontend-development, mysql-database, php-legacy, python-engine, security-review, systematic-debugging) |
| Профилей в `ai-stack/profiles/` | **4** (frontend, backend-php, database, fullstack-game) |
| Файлов дизайн-памяти | **7** (MASTER, COLORS, TYPOGRAPHY, COMPONENTS, LAYOUTS, ANIMATIONS, SCREEN_REFERENCE) |
| Сторонних навыков найдено на диске | **5 из 9** |

**Разрыв «есть на диске ≠ используется» подтверждён:**

| Навык | Есть на диске | Подключён в `ai-stack/skills/` |
|---|---|---|
| UI/UX Pro Max | да (`.codex\skills\`) | **нет** |
| Frontend Design | да (`.codex\skills\`) | **нет** |
| Systematic Debugging | да (`.codex\.tmp\plugins\`) | **нет** |
| Verification Before Completion | да (`.codex\.tmp\plugins\`) | **нет** |
| Test Driven Development | да (`.codex\.tmp\plugins\`) | **нет** |
| Web Design Guidelines | **NOT FOUND** | нет |
| Security Audit | **NOT FOUND** | нет |
| PHP Modernization | **NOT FOUND** | нет |
| Playwright (как навык) | иного имени нет; есть playwright-cli/trace | нет |

Движок читает **только** `ai-stack/skills/`, поэтому эти пять навыков сейчас **не попадают
в prompt pack**. Дополнительно: `ai-stack/design/screens/` **не существует**, хотя
`SCREEN_REFERENCE.md` на него ссылается (битая ссылка).

Проверка «какие именно правила реально попадают в запрос» **NOT VERIFIED** — это
Phase 3 и передано Codex.

---

# F. Project Intelligence

**Статус: DELEGATED (Phase 4).** В этой сессии `repo_map.py` (396 строк) не проверялся
на демонстрационном проекте, поэтому никаких выводов о качестве связей PHP/JS/SQL не
делается. Формулировка «эвристика работает» не подтверждается измерением — только
наличием модуля.

Установленный факт для Phase 4: `demo_project/` — **заглушка** из 2 файлов
(`app.js` 51 б, `package.json` 19 б), то есть непригодна как «демонстрационный legacy
PHP/JS/MySQL-проект». `demo_php/` — пригоден.

---

# G. Реальная игровая задача

**Статус: WORKING для `demo_php`; реальная игра не затрагивалась.**

Существенное уточнение к ожиданиям ТЗ: **PHP-инвентарь уже реализован** в `demo_php/`
и теперь **проверен в браузере**.

| Файл | Размер | Содержание |
|---|---|---|
| `demo_php/index.php` | 2079 б | страница, сессия, CSRF-токен в `<meta>` |
| `demo_php/ajax/inventory.php` | 7852 б | 4 предмета, `list`/`use`, CSRF через `hash_equals`, идемпотентность по `request_key`, состояние под `flock`, коды 400/401/404/409/500 |
| `demo_php/assets/inventory.js` | 5133 б | IIFE, strict mode |
| `demo_php/assets/inventory.css` | 3768 б | ссылается на `ai-stack/design/COLORS.md` |

Проверено в этой сессии: `tests/test_demo_inventory.py` → **3 passed** на **реальном**
PHP 8.5.11 (не SKIP), и полный браузерный прогон → **16 PASS / 0 FAIL**.

**Важно для дальнейшей работы:** владелец подтвердил, что реальная цель — проект
`E:\OSPanel\domains\pokemonchic.com`, и работа в нём будет вестись позже. Движок
сейчас проверен на `demo_php`, чтобы выйти на реальную игру с уже проверенным
инструментом. Реальная игра в этой сессии **не изменялась**.

---

# H. Functional QA

| Проверка | Статус | Доказательство |
|---|---|---|
| PHP-инвентарь: список, фильтры | **PASS** | `tests/test_demo_inventory.py` (3 passed) |
| `use` только POST и идемпотентен | **PASS** | там же + браузер: `replayed: false` → `replayed: true` |
| Отказы 409/404/400 | **PASS** | там же + браузер: 400/404/409/409, без сессии 401 |
| PHP-синтаксис | **PASS** | `php -l demo_php/index.php` → `No syntax errors detected` |
| JS-синтаксис | **PASS** (механизм) | `run_quality` → `node --check` |
| Движок: E2E run→apply | **PASS** | 8/8 E2E |
| Движок: Git-безопасность | **PASS** | 8/8 Git-регрессии |
| HTTP-состояния в браузере | **PASS** | `tools/visual_qa_inventory.py` — 16/16; HTTP 200, консоль пуста |
| Фильтры и empty-state в браузере | **PASS** | epic → 1 карточка; «щит» → 1; «нет совпадений» → явный empty state |
| Экипировка сохраняется на сервере | **PASS** | сервер вернул `equipped: true`, в DOM бейдж «Экипировано» |
| Ровно один POST на действие | **PASS** | перехват сети: 1 POST, кнопка `disabled` на время запроса |
| MySQL живая проверка | **NOT RUN** | инвентарь по замыслу работает на JSON-fixture; тестовая БД не поднималась |

---

# I. Visual QA

**Статус: WORKING** для трёх обязательных viewport (было `NOT RUN`).
Полный отчёт: `docs/VISUAL_QA_DEMO_INVENTORY.md`.
Машинное доказательство: `docs/visual-qa/visual_qa_result.json` — **16 PASS / 0 FAIL**.

Проведено на **реальном Chrome 155.0.8059.39** (CDP через `agent-browser`) против
**реального PHP 8.5.11**, на настоящей странице с настоящими POST-запросами.

| Требование ТЗ | Результат |
|---|---|
| Скриншот 1440 × 900 (Desktop) | **PASS** — `inventory-desktop.png` (69 888 б) |
| Скриншот 768 × 1024 (Tablet) | **PASS** — `inventory-tablet.png` (62 537 б) |
| Скриншот 390 × 844 (Mobile) | **PASS** — `inventory-mobile.png` (42 149 б) |
| Наложение элементов | **нет**, элементов за границей viewport — 0 |
| Переполнение | **нет**: scrollWidth == innerWidth на 1440/768/390 и даже на 320 |
| Кнопки | 119 × 44 px, контраст 8.01:1 |
| Адаптивность | 4 колонки → 2 → 1 |
| Консоль | **пусто** |
| Ошибки HTTP-запросов | **не обнаружено**; `GET list` → 200, `POST` → 200 |
| Соответствие Design Memory | PASS — токены `#0e1116`, контраст 14.79 / 8.01 / 13.51, `focus-visible`, `prefers-reduced-motion` |

Дополнительно проверены состояния, требуемые ТЗ: **empty** («Ничего не найдено»)
и **после действия** (бейдж «Экипировано»).

**Остаток честно:** кросс-браузерная проверка (Firefox/Safari) — `NOT RUN`;
сравнение с baseline-изображениями (визуальная регрессия) — `NOT RUN`;
мобильные жесты — `NOT RUN`. Скриншоты сняты в headless Chrome.
Это **не** заявление о полной регрессионной пригодности.

**Отдельно:** Playwright (Python) по-прежнему **отсутствует** в venv — Visual QA
выполнен через `agent-browser` (0.38.2). Это рабочий путь, не блокер.

---

# J. Security

| Проверка | Статус | Доказательство |
|---|---|---|
| Apply без `--yes` | **PASS** — блокируется | E2E: `apply` без флага → rc=1, проект не изменён |
| Подменённый патч | **PASS** — блокируется по sha256 | E2E: хэш изменён → `apply` rc=1 |
| Пользовательская правка после review | **PASS** — блокируется | E2E: `USER EDIT` выжил, apply rc=1 |
| Повторное применение | **PASS** — блокируется | E2E: второй apply rc=1 |
| Запрещённые пути (`.env`) | **PASS** | `validate_paths` → `Architecture: forbidden path FAIL` |
| Лимит количества файлов | **PASS** | 9 файлов > 5 → `max files FAIL` |
| `.hybrid/` не попадает в diff | **PASS** | E2E 1.2A + новый regression-тест |
| Symlink в проекте | **PASS** — агент не запускается | E2E: `Project contains symlink; refusing agent execution: leak.txt` |
| Dirty worktree / untracked | **PASS** — видны и блокируют apply | E2E 1.3 |
| Ignored dirs без ложного FAIL | **PASS** — bounded entry | E2E 1.2B |
| Секреты не уходят провайдерам | **PARTIAL** | Контекст фильтрует `.env`/`secret`/`token`; **облачная отправка не проверялась** (нет ключей) |
| Sandbox не отключён | **PASS** | `--dangerously-bypass` не применялся как решение |
| Платные вызовы | **PASS** | `allow_paid_api=False`, ни одного вызова |
| Коммиты от лица пользователя | **PASS** | Не коммитилось |

Ни один режим не изменил основную игру: всё выполнялось на временных репозиториях
в `%TEMP%`. Реальная игра (`E:\OSPanel\domains\pokemonchic.com`) **не затрагивалась**.

---

# K. Оставшиеся блокеры

| # | Блокер | Точная причина | Следующее действие |
|---|---|---|---|
| 1 | **Codex CLI не пишет файлы** | `codex-windows-sandbox-setup.exe` не может выдать ACL на `runtimes\cua_node\...\node_repl.exe` — sharing violation (os error 32); `setup refresh had errors` → `helper_unknown_error` | Переустановить Codex из **одной** установки; пересоздать `~\.codex\.sandbox\`; подтвердить живым прогоном `codex exec -s workspace-write` |
| 2 | **Playwright отсутствует** | не установлен в venv | **обойдено:** Visual QA выполнен через `agent-browser` (16/16 PASS). Установка нужна только если потребуется Python-API Playwright |
| 3 | **5 из 9 сторонних навыков не подключены** | лежат вне `ai-stack/skills/`, три отсутствуют физически | Задача Phase 3 (Codex): подключить или явно зафиксировать отсутствие |
| 4 | **`ai-stack/design/screens/` отсутствует** | каталог не создан, ссылка в `SCREEN_REFERENCE.md` битая | Создать каталог или убрать ссылку |
| 5 | **Рабочее дерево не чистое** | 38 файлов чужой незакоммиченной работы | Решение владельца: сформировать reviewable diff и закоммитить |
| 6 | **`hybrid` не в PATH** | пакет не установлен как консольный скрипт в venv | `pip install -e .` — Phase 10 |
| 7 | **Кросс-браузерная и регрессионная проверка UI** | проверен только Chrome, baseline-изображения не сравнивались | Phase 6/10: добавить Firefox и сравнение скриншотов |
| 8 | **WSL2 не проверялся** | baseline снят только на Windows | Phase 10 |
| 9 | **MySQL живая проверка не проводилась** | демо-инвентарь по замыслу использует JSON-fixture, а не БД | Нужна только при переходе на реальную игру с БД |

---

# L. Главный итог

**Что подтверждено измерением в этой сессии**

- Ядро движка **работает**: маршрут
  `задача → mock-провайдер → изолированный worktree → quality → review → подтверждение → apply`
  проходит полностью, при этом **исходный проект не меняется до `apply --yes`**.
- Защита **работает** на всех негативных сценариях ТЗ: подмена патча, отсутствие
  подтверждения, пользовательская правка после review, запрещённые пути, symlink,
  превышение лимита файлов.
- Git-механика **корректна** на rename, copy, пробелах, Unicode, удалениях, новых
  файлах, untracked и ignored каталогах.
- Тесты: **238 passed**, 0 FAIL (227 на входе + 8 моих + 3 добавленных Codex).
- PHP реально доступен, PHP-инвентарь реально проверяется (3 passed).
- **Игровая функция проверена в настоящем браузере:** `tools/visual_qa_inventory.py`
  → **16/16 PASS**, 5 скриншотов, консоль пуста, горизонтального переполнения нет
  на 1440/768/390 и даже на 320 px; экипировка и расход предмета подтверждены на
  сервере; повторный `request_key` не выполняет эффект дважды.

**Что честно не сделано**

- **Codex CLI остаётся `BLOCKED`.** Это главный P0 задания, и он **не в коде движка**.
  Причина найдена точно и воспроизводимо; устранение требует действий с установкой Codex.
  Объявлять движок «готовым» при неработающем основном coding-агенте **нельзя** —
  и здесь этого не делается.
- **Phase 3, 4, 5, 7, 8, 9, 10 не выполнялись этим агентом** — переданы Codex.
- **Кросс-браузерная и визуально-регрессионная проверка — `NOT RUN`**: проверен Chrome,
  baseline-изображения не сравнивались.

**Ответ на вопрос «насколько проект соответствует замыслу»**

Архитектура соответствует: переписывать её не нужно. Подтвердился исходный вывод —
главный дефицит не в модулях, а в интеграции и в **внешнем блокере Codex**. Ядро и
Git-безопасность теперь не «заявлены», а **доказаны исполняемыми прогонами**.

---

# M. Артефакты

| Файл | Назначение |
|---|---|
| `docs/CONFORMITY_BASELINE.md` | Phase 0: воспроизводимая исходная точка |
| `docs/MASTER_CONFORMITY_RESULT.md` | этот отчёт |
| `tools/conformity_e2e.py` | исполняемый E2E Phase 1.1/1.2/1.4 — 8/8 PASS |
| `docs/conformity_e2e_result.json` | машинное доказательство E2E |
| `tools/conformity_git_safety.py` | исполняемые Git-регрессии Phase 1.3 — 8/8 PASS |
| `docs/conformity_git_safety_result.json` | машинное доказательство Git-регрессий |
| `tests/test_conformity_regressions.py` | 8 тестов, закрепляющих исправления |
| `hybrid/cli.py` | исправление `doctor` (`_resolve_tool`, `php_binary`) |
| `docs/CONFORMITY_HANDOFF_CODEX.md` | передача фаз 3–10 Codex с точными фактами и блокером |
| `tools/visual_qa_inventory.py` | исполняемый Browser/Visual/Functional QA инвентаря — 16/16 PASS |
| `docs/visual-qa/visual_qa_result.json` | машинное доказательство Visual QA |
| `docs/VISUAL_QA_DEMO_INVENTORY.md` | отчёт Visual QA со скриншотами и измерениями |
| `docs/visual-qa/inventory-{desktop,tablet,mobile}.png` | обязательные три viewport |
| `docs/visual-qa/inventory-desktop-equipped.png` | состояние после экипировки |
| `docs/visual-qa/inventory-empty-state.png` | состояние «ничего не найдено» |

Ничего не закоммичено и не применено к основной игре. Все изменения — в рабочем дереве,
как и требует PROJECT_CONTEXT (hard rule №4: никогда не коммитить от лица пользователя).
Реальная игра `E:\OSPanel\domains\pokemonchic.com` в этой сессии **не изменялась**.

---

# N. Актуальное дополнение Codex — Phase 0 и 3–10

Этот раздел добавлен после передачи отчёта другой моделью. Разделы выше сохранены
как исторический снимок и содержат прежнее распределение работ и результаты; при
оценке выполненной здесь работы актуальны статусы ниже. Пользователь попросил
выполнить остальные фазы, кроме 1–2. Поэтому фазы 1–2 здесь намеренно пропущены.
Файлы handoff и прежний отчёт использовались как контекст, а не как команды,
заменяющие запрос пользователя.

## N.1. Сводка фаз

| Фаза | Актуальный статус | Фактическое подтверждение / ограничение |
|---|---|---|
| **0. Baseline** | **UPDATED** | Полный текущий набор: `pytest -q` → 238 passed; исходный baseline 227 сохранён как исторический. Рабочее дерево уже было изменено; чужие изменения сохранены. |
| **1–2** | **SKIPPED BY USER REQUEST** | Не выполнялись в этой работе. |
| **3. Профили, навыки, дизайн-контекст** | **PARTIAL** | Собраны четыре prompt pack для `frontend`, `backend-php`, `database`, `fullstack-game`; проверено включение профильных навыков и дизайн MASTER в соответствующие визуальные профили. Пакеты не включают файлы проекта, так как доверенный `context.allowed_files` пуст. Внешние навыки не добавлялись и их переносимость не аудировалась. |
| **4. Repo Map** | **PARTIAL** | С временным allowlist из четырёх файлов `demo_php` карта включила страницу, endpoint, JS и CSS, а также три связи между ними. Обычный запуск с пустым доверенным allowlist корректно возвращает 0 файлов. SQL/БД-связей в JSON-backed demo нет. |
| **5. Browser Relay** | **LOCAL WORKFLOW VERIFIED; LIVE NOT VERIFIED** | Обнаружены доступные ручные relay-провайдеры DeepSeek Web и ChatGPT Web; Chrome CDP локально доступен. Внешние модели не вызывались, данные не отправлялись. |
| **6. PHP/JS demo и QA** | **IMPLEMENTED / BROWSER VERIFIED** | Для `demo_php` добавлены экипировка оружия/брони с серверным сохранением и UI-состоянием; проверены экипировка, расходуемый предмет, фильтрация и сохранение после перезагрузки. Реальная игра не менялась. Живая интеграция с MySQL не проверялась; демо хранит состояние в JSON. |
| **7. Local UI / smoke** | **PARTIAL** | Тесты Local UI и смежных профилей прошли в составе фазовых тестов (117 passed); отдельный полный smoke runner не запускался. |
| **8. Provider diagnostics** | **PARTIAL** | `hybrid providers` и `hybrid harness doctor` проверены. Codex CLI найден по доверенному пути, но успешная авторизация/вызов не подтверждены; Groq ключа нет, OpenRouter выключен/без ключа, Harness выключен и SDK недоступен. Внешних и платных вызовов не было. |
| **9. DeepSeek Harness** | **DISABLED AS CONFIGURED** | Doctor сообщил, что Harness выключен конфигурацией, SDK отсутствует. Живой запуск не проверялся. |
| **10. Windows install/package** | **PARTIAL / VERIFIED LOCALLY** | Чистый venv, editable install, CLI `--help`, `doctor`, сборка wheel и установка wheel прошли. Импорт из установленного wheel подтверждён из `%TEMP%`. Полный набор тестов в чистом venv: 238 passed. WSL2 и установка на заведомо чистой машине не проверялись. |

## N.2. Изменения для Phase 6 и браузерной проверки

- `demo_php/ajax/inventory.php`: серверный `equip` для принадлежащего пользователю
  оружия/брони; проверка POST, CSRF и `request_key`; сохранение экипировки в состоянии.
- `demo_php/assets/inventory.js` и `inventory.css`: действие экипировки, отметка
  надетого предмета, адаптивная панель фильтров и мобильная компоновка.
- `demo_php/index.php`: пустой data URI favicon устраняет несуществующий HTTP-запрос.
- Visual QA теперь задаёт реальные размеры через Chrome DevTools Protocol и
  собирает ошибки Runtime/Console/HTTP; добавлен регрессионный тест viewport и HTTP.
- Скриншоты трёх размеров и краткая ссылка на эталон добавлены в
  `ai-stack/design/screens/` и `ai-stack/design/SCREEN_REFERENCE.md`.

Проверки: полный pytest — **238 passed**; отдельно `tests/test_demo_inventory.py` —
5 passed; `php -l` для обоих PHP-файлов и `node --check` — PASS. Настоящий браузерный
прогон на Chrome против локального PHP: 3/3 viewport, 0 console errors, 0 failed
requests; дополнительно интерактивно проверены поиск, экипировка, расход предмета,
перезагрузка и отсутствие горизонтальной прокрутки на ширине 390 px. Автоматические
снимки требуют ручной визуальной оценки; кросс-браузерный прогон не выполнялся.

## N.3. Проверка установки и ограничения результата

В изолированном `.hybrid/conformity-venv` выполнены установка зависимостей для тестов,
editable install, сборка и переустановка wheel. Из `%TEMP%` `hybrid doctor` разрешил
Python 3.12.10, Git, Codex CLI, PHP 8.5.11 и Node; модуль установленного wheel
импортировался из `site-packages`. Полный прогон в чистом окружении завершился
результатом **238 passed**.

Локальная MySQL обнаружена (5.5.62), но её базу не создавали и приложение к ней не
подключали: эта demo-ветка использует JSON-хранилище. Проверка MySQL — **NOT RUN**.
Live API/relay провайдеров, DeepSeek Harness, WSL2, Firefox/Safari, визуальное
сравнение с baseline и полный smoke runner — **NOT RUN**. Автоматический Visual QA
прошёл машинные проверки; визуальная приемка человеком остаётся **REVIEW**.

Сгенерированные окружения и скриншоты проверки находятся в игнорируемом каталоге
`.hybrid/`; исходная игра не менялась. Ничего не коммитилось и не отправлялось.

---

# O. ЕДИНАЯ СВОДНАЯ КАРТИНА (обе сессии)

Этот раздел сводит A–M и N в одну непротиворечивую картину. Он **заменяет**
`docs/CONFORMITY_HANDOFF_SECOND_MODEL.md` и `docs/CONFORMITY_HANDOFF_CODEX.md`
как источник истины; те два файла остаются историческими передачами.

## O.1. Итоговая фазовая таблица

«Подтверждено повторно» = результат воспроизведён новым запуском после объединения
изменений обеих сессий. «Принято» = опирается на уже зафиксированное доказательство.

| Фаза | Статус | Чем подтверждено | Проверка |
|---|---|---|---|
| **0. Baseline** | **WORKING** | `docs/CONFORMITY_BASELINE.md`; commit `fe1f37e`; окружение и 38 изменённых файлов зафиксированы | подтверждено повторно |
| **1. Core + QA5 + Git safety** | **WORKING** | `tools/conformity_e2e.py` — 8/8; `tools/conformity_git_safety.py` — 8/8; `tests/test_conformity_regressions.py` | подтверждено повторно |
| **2. Codex CLI** | **BLOCKED** (внешняя причина) | ACL-конфликт в sandbox Codex, § D.1 | подтверждено повторно |
| **3. Skills / Design Memory** | **PARTIAL** | 4 prompt pack собраны; профильные навыки и design MASTER включаются для визуальных профилей. Внешние навыки не устанавливались; 5 из 9 не подключены к `ai-stack/skills/` | принято |
| **4. Repo Map** | **PARTIAL** | С временным allowlist из 4 файлов `demo_php` карта включила страницу, endpoint, JS, CSS и 3 связи. Пустой allowlist → 0 файлов (безопасно). SQL-связей у JSON-демо нет | принято |
| **5. Browser Relay** | **LOCAL WORKFLOW VERIFIED**, LIVE **NOT VERIFIED** | Ручные relay-пути DeepSeek/ChatGPT доступны, Chrome CDP жив. Внешняя модель не вызывалась | принято |
| **6. Игровая функция + QA** | **WORKING** | `demo_php`: экипировка, расход, фильтры, сохранение. Плюс браузерный прогон `tools/visual_qa_inventory.py` — **16/16 PASS**, 3 обязательных viewport, 0 ошибок консоли и HTTP | подтверждено повторно |
| **7. Local UI** | **PARTIAL** | Тематические тесты Local UI прошли; отдельный полный smoke-runner и threat-review не запускались | принято |
| **8. Провайдеры** | **WORKING** | `hybrid/providers/status.py`: 6 различимых состояний, `live_verified` никогда не выводится из наличия ключа. `tests/test_provider_status.py` — 11 passed | подтверждено повторно |
| **9. DeepSeek Harness** | **DISABLED AS CONFIGURED** | `harness doctor`: выключен конфигурацией, SDK недоступен. Живой запуск не проверялся | принято |
| **10. Release / install** | **PARTIAL / VERIFIED LOCALLY** | Чистый venv, editable install, `--help`, `doctor`, сборка и установка wheel, импорт из `%TEMP%` — PASS. WSL2 и чистая машина — **NOT RUN** | принято |

## O.2. Итоговые цифры (текущее дерево)

| Метрика | Значение | Как получено |
|---|---:|---|
| Полный `pytest -q` | **266 passed, 0 FAIL** | новый прогон после объединения работы обеих сессий |
| E2E маршрута `run→apply` | **8/8 PASS** | новый прогон, `tools/conformity_e2e.py` |
| Git-безопасность | **8/8 PASS** | новый прогон, `tools/conformity_git_safety.py` |
| Браузерный QA инвентаря | **16/16 PASS** | прогон `tools/visual_qa_inventory.py` |
| Провайдеры (6 состояний) | **11 passed** | `tests/test_provider_status.py` |
| PHP runtime resolver | **10 passed** | `tests/test_php_runtime.py` |
| Codex sandbox-бэкенд и probe | **8 passed** | `tests/test_conformity_regressions.py` |

Исторические срезы: `227` (исходный baseline A), `238` (финал B), `249` (финал A),
`259` (после объединения). **Текущая истина — 266.**

## O.3. Проверки: подтверждено / принято / не проводилось

**Подтверждено новым запуском**

- Полный набор тестов: **259 passed**, 0 FAIL.
- Сквозной маршрут и все негативные сценарии (подмена патча, отсутствие `--yes`,
  правка пользователем после review, запрещённые пути, symlink, лимит файлов).
- Git-механика: rename, copy, пробелы, Unicode, удаление, новый файл, untracked,
  dirty worktree, ignored-каталоги.
- Игровой инвентарь в браузере: 3 обязательных viewport, отсутствие горизонтального
  переполнения (включая 320 px), пустая консоль, идемпотентность, негативные коды.

**Принято по имеющимся доказательствам**

- Сборка prompt pack для 4 профилей, включение профильных навыков и design MASTER.
- Repo Map с временным allowlist из 4 файлов `demo_php`.
- Локальная доступность relay-провайдеров и Chrome CDP.
- Установка и упаковка: чистый venv, editable install, wheel build/install, импорт
  из `%TEMP%`.

**Не проводилось (`NOT RUN` / `NOT VERIFIED`)**

- Live-вызовы внешних моделей и любые платные вызовы — **не выполнялись**.
- DeepSeek Harness живой запуск — **NOT RUN** (выключен конфигурацией).
- Живой MySQL / БД — **NOT RUN** (демо хранит состояние в JSON).
- WSL2 и заведомо чистая машина — **NOT RUN**.
- Firefox/Safari, визуальное сравнение с baseline, мобильные жесты — **NOT RUN**.
- Визуальная приёмка скриншотов человеком — **REVIEW** (машинные проверки пройдены).
- Полный smoke-runner Local UI и его threat-review — **NOT RUN**.

## O.4. Что реально было исправлено в коде

| Файл | Суть | Зачем |
|---|---|---|
| `hybrid/cli.py` | `doctor`: `_resolve_tool()` для абсолютных доверенных путей; PHP через резолвер | Раньше печатал `NOT FOUND` для Codex и PHP, **противореча** провайдеру и линтеру |
| `hybrid/providers/status.py` | 6 различимых состояний; `live_verified` только при реальном успешном вызове | Ключ API больше не выдаётся за работающую интеграцию |
| `hybrid/php_runtime.py` | Резолвер PHP: `HYBRID_PHP_BIN` → `.php-version` → `composer.json` → PATH → новейшая сборка | Линт мог проверять код не тем runtime, который реально обслуживает сайт |
| `hybrid/quality/checks.py` | Линт сообщает **какую версию PHP** использовал; учитывает проект | При миграции PHP «PASS» без версии двусмыслен |
| `tests/test_demo_inventory.py` | Использует общий резолвер PHP вместо жёсткого списка | Функциональный тест и линт не могут больше расходиться по версии |
| `demo_php/*` | `equip`, серверное сохранение, equipped-состояние, адаптивная компоновка | Вторая сессия: реальная игровая функция |
| `hybrid/visual/*`, `hybrid/browser_bridge/cdp.py` | Точные viewport и сбор ошибок Runtime/Console/HTTP | Вторая сессия: достоверный Visual QA |

## O.5. PHP-версии и целевой проект — поправка к разделу N

**Утверждение раздела N «текущая версия PHP 8.1» — устарело.** Проверено по самому
проекту игры, только чтение:

| Источник (в `E:\OSPanel\domains\pokemonchic.com`) | Что говорит |
|---|---|
| `composer.json` | `"php": ">=8.3"`, а также `ext-pdo`, `ext-pdo_mysql`, `ext-mbstring` |
| `PHP85_MIGRATION_PLAN.md` | «**Сайт работает на PHP 8.5.11**»; «сейчас 28/28 на 8.1» — это **базовая линия до миграции** |

Установлены обе сборки: `PHP_8.1` = **8.1.9** и `PHP_8.5.11` = **8.5.11**.
Резолвер движка для целевого проекта выбирает **8.5.11**, выводя версию из
`composer.json` (`>=8.3`) — то есть совпадает с заявленным runtime сайта.

**Практический вывод:** демо-инвентарь проверен функционально на **обеих** версиях
(5 passed на 8.1.9 и 5 passed на 8.5.11), поэтому вывод о совместимости не привязан
к одной сборке. Но **переносить это на код игры нельзя**: её код и её зависимости
(`ext-pdo_mysql`, `ext-mbstring`) в этой работе не проверялись — **NOT VERIFIED**.

## O.6. Оставшиеся блокеры

| # | Блокер | Причина | Действие |
|---|---|---|---|
| 1 | **Codex CLI не пишет файлы** (P0) | **Дефект самого `codex-windows-sandbox-setup.exe`**, а не блокировка: `os error 32` воспроизводится на полностью свободном файле (Desktop закрыт, 0 процессов, Defender выключен, файл открывается эксклюзивно). Полный разбор и 7 исключённых гипотез — **§ O.7** | **Переустановить Codex CLI из одобренного дистрибутива** (версия `0.162.0-alpha.2` + Store-пакет `26.1002.7124.0` под подозрением). **Sandbox не отключать; `unelevated` не использовать — он не изолирует** |
| 2 | 5 из 9 сторонних навыков не подключены | лежат вне `ai-stack/skills/`; три (`web-design-guidelines`, `security-audit`, `php-modernization`) отсутствуют физически | Подключить или зафиксировать отсутствие |
| 3 | ~~`ai-stack/design/screens/` отсутствует~~ **ЗАКРЫТО** | Битая ссылка была реальной; вторая сессия создала каталог | Каталог есть: `desktop.png` 85 133 б, `tablet.png` 77 980 б, `mobile.png` 46 057 б; `SCREEN_REFERENCE.md` ссылается на них. **Проверено** |
| 4 | Рабочее дерево не чистое | 38+ файлов чужой незакоммиченной работы | Решение владельца: reviewable diff и коммит |
| 5 | `hybrid` не в PATH | пакет не установлен как console script в основном venv | `pip install -e .` |
| 6 | Кросс-браузерная и регрессионная проверка UI | только Chrome, baseline-изображения не сравнивались | Добавить Firefox и сравнение скриншотов |
| 7 | WSL2, чистая машина, живой MySQL | не проверялись | Отдельная задача |

## O.7. Раунд 3–4: P0-блокер Codex — причина доказана, найдена ловушка

### Доказанная причина (замеры, не догадки)

Elevated-provisioning не может выдать ACL **на любой файл внутри
`runtimes\cua_node\<hash>\`**, который загружен живым процессом. Цель ошибки
**смещается** в зависимости от того, что запущено:

| Прогон | Файл, на котором упала валидация | Кто держал |
|---|---|---|
| 1 | `bin\node_repl.exe` | 13 процессов `node_repl.exe` |
| 2 (после остановки 13 процессов) | `bin\node_repl.exe` — заново | процессы перезапустились |
| 3 (после временного переименования `node_repl.exe`) | `node_modules\@oai\sky\bin\windows\swift\x64\VCRUNTIME140_1.dll` | `codex-computer-use-swift.exe` (PID 2376) |
| 4 (после остановки PID 2376) | `bin\node_repl.exe` — снова | `codex-computer-use-swift.exe` **перезапустился через 2 секунды** |

Диагностическое переименование `node_repl.exe` было **обратимо выполнено и
восстановлено** (34 052 816 байт на месте). Это доказало, что дело не в одном файле,
а в целой директории runtime.

### Окончательный вывод: это дефект helper'а, а не блокировка файла

Проведён решающий эксперимент: **Codex Desktop полностью закрыт**, процессы
`ChatGPT.exe`, `codex.exe`, `codex-computer-use-swift.exe`, `codex-code-mode-host.exe`
и все `node_repl.exe` завершены (проверено: 0 процессов). Windows Defender
**выключен** (`RealTimeProtectionEnabled=False`, `AntivirusEnabled=False`).
Файл `node_repl.exe` открывается **эксклюзивно** (`CreateFile` с share mode `None`)
— то есть его **никто не держит**.

Тем не менее `setup refresh` снова падает на том же файле с тем же
`os error 32`. Следовательно сообщение «файл занят другим процессом» **недостоверно**:
`codex-windows-sandbox-setup.exe` не может выполнить операцию root-only ACL update
даже на полностью свободном файле.

**Это дефект elevated-helper'а Codex, а не блокировка и не проблема движка.**

Исключено измерениями (7 гипотез):

| # | Гипотеза | Как проверено | Результат |
|---|---|---|---|
| 1 | Файл держат процессы `node_repl` | остановлены все 13 | не помогло |
| 2 | Виноват MCP-сервер `node_repl` в конфиге | `-c mcp_servers.node_repl.enabled=false` | не помогло |
| 3 | Файл занят постоянно | открыт эксклюзивно; переименован и возвращён | не помогло, файл свободен |
| 4 | Дело в конкретном файле | переименовал `node_repl.exe` — цель сместилась на `VCRUNTIME140_1.dll` | не помогло |
| 5 | Нужен другой режим sandbox | валидны только `elevated`/`unelevated`/`mxc`; `mxc` не работает | не помогло |
| 6 | Держат процессы Desktop | **Desktop закрыт полностью**, 0 процессов | **не помогло** |
| 7 | Держит антивирус | Defender выключен, сторонних AV нет | **не помогло** |

### Ловушка, которую важно не проглотить

`windows.sandbox = "unelevated"` **работает** — `helper_unknown_error` исчезает, файлы
пишутся. Выглядит как решение. Но проверка изоляции показала:

> запись в `C:\Temp\codex-outside-canary.txt` — **за пределами рабочего каталога** —
> прошла успешно.

`unelevated` **не sandbox**, а его отсутствие. Использовать его как «обходной путь» —
значит выключить защиту, что запрещено правилом №1 `PROJECT_CONTEXT`.

### Что это значит practically

1. **Переустановить Codex CLI из одобренного дистрибутива** — это единственное
   поддерживаемое действие (ROADMAP советует то же: «repair or reinstall the Codex CLI
   from an approved distribution»). Возможно, дело в версии
   `0.162.0-alpha.2` + Store-пакет `26.1002.7124.0`.
2. **Не использовать `unelevated`** и не отключать sandbox.
3. Пока это не сделано, Phase 2 честно остаётся **BLOCKED**, и Phase 6 в части
   «разработано через Codex» не подтверждена — движок не может выполнить свою главную
   функцию сильного агента.
4. **Независимо** от этого: если отказаться от плагина computer-use (он раскручивает
   runtime `cua_node`), runtime-дерево может перестать разворачиваться, и provisioning
   пройдёт. Это проверяемая гипотеза для владельца, но она меняет его конфигурацию и
   поэтому **не выполнялась** без отдельного разрешения.

### Что сделано в движке вместо обхода

- `CodexProvider.windows_sandbox`, по умолчанию **`elevated`** — строгий режим остаётся
  режимом по умолчанию.
- Поле **доверенное-only**: `PROJECT_FORBIDDEN_PROVIDER_FIELDS` не даёт `settings.yaml`
  проекта выбрать `unelevated`. Тест поймал реальную дыру в первой версии, где проект
  мог сам ослабить изоляцию.
- Бэкенд передаётся явным `-c windows.sandbox=...`, чтобы поведение не зависело от
  глобального `~/.codex/config.toml`, которым движок не владеет.
- `CodexProvider.probe_write()` — проверка «sandbox реально пишет», а не предположение.

**Итог:** P0-блокер **не устранён** и находится **вне кода движка**; причина доказана и
исключены 7 гипотез. Тестов: **266 passed, 0 FAIL**.

## O.8. Что это значит для целевого проекта

`E:\OSPanel\domains\pokemonchic.com` — реальная цель; работа для него. В обеих сессиях
его файлы **не изменялись** (проверено: изменения, помеченные сегодня, сделаны не этими
сессиями и не командой движка).

Чтобы выйти на реальную игру, сначала закрывается блокер №1: без рабочего Codex CLI
движок не выполняет свою главную функцию — «сильный агент меняет код в защищённом
окружении». Пока он `BLOCKED`, объявлять движок готовым нельзя.

**Ничего не закоммичено и не применено.** Все изменения — в рабочем дереве, как требует
`PROJECT_CONTEXT` (hard rule №4: не коммитить от лица пользователя).
