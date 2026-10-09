# Browser AI Bridge

Работа с сильной моделью через её **официальный веб-чат**, когда API-ключа нет.
Это режим с участием человека (relay): движок готовит запрос, вы сами открываете
сайт, сами входите в свой аккаунт, сами отправляете запрос и сами возвращаете
ответ. Движок проверяет ответ, показывает diff и применяет изменения только
после вашего подтверждения.

```
hybrid browser prepare "Сделай современный инвентарь" --provider deepseek --profile frontend
hybrid browser open    BTASK-XXXXXXXX
hybrid browser prompt  BTASK-XXXXXXXX
hybrid browser import  BTASK-XXXXXXXX --file answer.md
hybrid browser review  BTASK-XXXXXXXX
hybrid apply TASK-XXXXXXXX --yes
```

## Команды

| Команда | Что делает |
|---|---|
| `hybrid browser providers` | список браузерных провайдеров и режимов |
| `hybrid browser prepare "<задача>" [--provider deepseek\|chatgpt] [--profile ...]` | создаёт задачу, собирает Context Pack и запрос; ничего не отправляет |
| `hybrid browser open <BTASK-ID>` | открывает официальный сайт в вашем браузере |
| `hybrid browser prompt <BTASK-ID>` | печатает подготовленный запрос |
| `hybrid browser import <BTASK-ID> --file answer.md` | импортирует ответ (также `--text "..."` или пайп) |
| `hybrid browser review <BTASK-ID>` | статус, файлы, проверки, предупреждения, команда apply |
| `hybrid browser diff <BTASK-ID>` | полный diff предложенного патча |
| `hybrid browser request-review <BTASK-ID> [--reviewer chatgpt]` | готовит запрос на независимое ревью вторым провайдером |
| `hybrid browser history` | все браузерные задачи |
| `hybrid browser cancel <BTASK-ID>` | отменяет локальную задачу |

## Живая сессия (CDP)

Последние команды управляют **уже открытым, уже залогиненным** Chrome через
DevTools Protocol. Движок не читает cookies и токены и не копирует профиль: вы
один раз входите в окне, которое он открыл.

| Команда | Что делает |
|---|---|
| `hybrid browser launch [--url ...]` | запускает общий профиль Chrome с `--remote-debugging-port` |
| `hybrid browser status` | сессия запущена, и принадлежит ли порт этому профилю |
| `hybrid browser at --url URL [--check JS] [--shot PATH]` | открывает страницу и печатает title/URL/значение выражения |
| `hybrid browser read [--json] [--save PATH]` | диагностика страницы и последний ответ |
| `hybrid browser say "текст" [--send]` | вставляет текст в composer (и по `--send` отправляет) |
| `hybrid browser chat ...` | полный цикл: prompt → проверка вставки → отправка → ожидание нового ответа → импорт |

## Два режима: manual relay и automation

Обе группы команд живут под `hybrid browser`, но у них разные модели доверия:

| Режим | Команды | Кто действует |
|---|---|---|
| **Manual relay** (по умолчанию, не изменился) | `prepare`, `open`, `prompt`, `import`, `review`, `diff`, `request-review`, `history`, `cancel` | Вы сами вставляете prompt и сами копируете ответ. Движок ничего не отправляет. |
| **Automation** (явно, живой Chrome через CDP) | `launch`, `status`, `at`, `read`, `say`, `chat` | Движок печатает в вашей залогиненной вкладке и читает ответ — но только при явном `--send`. |

Правила automation, зашитые в код, а не в договорённость:

- `browser chat` **без `--send` — это dry run**: текст попадает в composer и остаётся там.
- Уже провалидированный результат **не заменяется неявно**: нужен `--force-import`.
- Ответ, который всё ещё стримился, когда истёк `--timeout`, **отклоняется**: нужен `--allow-partial`.
- Ответ читается только из сообщения, появившегося **после** отправки (baseline).
- Login wall / CAPTCHA / лимит останавливают прогон **до** ввода текста.

## `hybrid browser chat`

```bash
hybrid browser chat --task BTASK-XXXXXXXX --send [--new-conversation]
hybrid browser chat --file prompt.md --send --continue https://chatgpt.com/c/...
hybrid browser chat --task BTASK-XXXXXXXX --send --keep-conversation
hybrid browser chat --task BTASK-XXXXXXXX --send --force-import
hybrid browser chat --task BTASK-XXXXXXXX --send --allow-partial   # сознательно принять обрезанный ответ
```

Автоматизация работает как явная state machine:

```
IDLE → COMPOSER_READY → PROMPT_INSERTED → SUBMITTED → ASSISTANT_STARTED
     → STREAMING → STREAM_FINISHED → ANSWER_EXTRACTED → FAILED
```

Ключевые свойства:

- **Опрос адаптивный, а не раз в 5 секунд.** Пока страница реагирует — 150 мс,
  пока модель думает — 500 мс, во время длинного стрима — 1.5 с. Никаких
  фиксированных `sleep` вместо ожидания условия: каждый шаг ждёт предикат с
  дедлайном, а на таймауте печатает последнее состояние страницы.
- **Ответ читается только из нового сообщения.** Перед отправкой сохраняется
  baseline (URL, число assistant-сообщений, ключ и хеш последнего). Ответом
  считается только сообщение, которого до отправки не было.
- **Fail fast.** Login wall, CAPTCHA и лимиты распознаются до отправки, а не
  после «send button was not available».
- **Проверка вставки.** Текст сверяется по длине; при большом prompt (>20 000
  символов) он вставляется порциями по 4000 с проверкой.
- **Новая беседа убирается из списка после импорта.** Для `--new-conversation`
  и запуска на корневом `https://chatgpt.com/` движок после принятого импорта
  архивирует только созданную этим запуском беседу. Архивация обратима; ответ,
  provenance и артефакты остаются в `.hybrid/tasks/...`. `--continue` никогда
  не архивирует открытую беседу. Если беседу нужно оставить, укажите
  `--keep-conversation`. При несовпадении URL, пропаже строки в истории или
  изменении меню команда откажется выбирать другой чат и напечатает warning.
- **Частичный ответ не выдаётся за готовый.** «Текст перестал меняться» — не
  доказательство: reasoning-модель может думать секундами, а на время
  веб-поиска кнопка Stop может быть не видна. Поэтому конец генерации
  подтверждается явно — кнопка Stop наблюдалась и исчезла. Если её не видели ни
  разу, движок ждёт заметно дольше и всё равно ставит `complete=false`, а `chat`
  отказывается такой ответ импортировать без `--allow-partial`.
- **Целостность prompt'а проверяется по содержимому, а не по длине.** Длина
  врёт в обе стороны: `innerText` схлопывает пустые строки (prompt из 12
  символов возвращается как 21), а допуск в 5% на prompt'е в 20 000 символов
  молча разрешил бы потерять 1000. Поэтому потеря символов — всегда ошибка,
  рост — нормальная нормализация, а первые и последние символы исходника должны
  совпасть.
- **Прогресс виден.** Тайминги по стадиям (`diagnose`, `insert_prompt`,
  `submit`, `wait_for_start`, `streaming`, `extract`) печатаются и сохраняются.

Селекторы живут в реестре `hybrid/browser_bridge/browser_state.py`
(`SELECTORS`): у каждого — fallback'и и уверенность, а `hybrid browser read`
печатает, каким именно селектором найден каждый элемент.

### Горячий путь не читает переписку

Пробник страницы существует в двух вариантах. Полный (`signals=checked`) читает
текст страницы, чтобы распознать login wall / CAPTCHA / лимит, и вызывается один
раз за попытку, а также при разборе ошибки. Дешёвый (`signals=not read`) не
читает текст вообще и используется во время стрима, где опрос идёт каждые 150 мс.
Дешёвый пробник не имеет права утверждать «login wall нет»: его поле
`signals_checked=false`, и `fatal_blockers()` на нём всегда пуст.

### Артефакты и что в них попадает

```
.hybrid/tasks/<TASK-ID>/browser/
  prompt.json         # что именно отправили: sha256, source, длина
  answer.json         # что импортировали: sha256, ключ сообщения, URL беседы, complete
  timing.json         # тайминги по стадиям
  state.json          # состояние страницы, selector report, причина падения
  screenshot.png      # как выглядела страница (ПИКСЕЛИ СТРАНИЦЫ, не редактируются)
  dom-snippet.html    # ОБЕЗЛИЧЕННЫЙ скелет DOM
  history/            # предыдущие answer-*.json при --force-import (последние 3)
```

`dom-snippet.html` — это skeleton, а не дамп страницы. Из него удаляются:

- все текстовые узлы (переписка, черновик prompt, заголовки чатов в сайдбаре);
- `<script>`, `<style>`, `<head>`, `<noscript>`, `<template>`, `<svg>`, `<iframe>`;
- все атрибуты, кроме allow-list (`data-testid`, `data-message-author-role`,
  `data-message-id`, `role`, `id`, `type`, `class`, `contenteditable`,
  `disabled`, `aria-*`-состояния, `data-state`). В частности **не** сохраняются
  `data-csrf-token`, `value`, `href` на беседу и `aria-label` — на реальном сайте
  именно в `aria-label` кнопки аккаунта лежат имя и email.

В `state.json` и `timing.json` URL и заголовок страницы тоже обезличиваются:
вместо `https://chatgpt.com/c/68f1…` пишется `https://chatgpt.com/c/<id>`, а
вместо заголовка — его длина. На ChatGPT `document.title` — это имя беседы,
автоматически выведенное из вашего первого сообщения, поэтому в диагностику оно
не попадает. Полный URL и заголовок видит только человек в выводе
`hybrid browser read` — это интерактивный текст, а не файл.

Единственное место, где ссылка на беседу хранится осознанно, — `answer.json` и
`metadata.json` задачи (`conversation_url`). Без неё нельзя ответить на вопрос
«из какого чата пришёл этот ответ» и нельзя продолжить беседу через
`--continue`. Это провенанс, а не диагностика.

Размер `dom-snippet.html` ограничен 120 000 символов. Файлы перезаписываются на
каждом прогоне одной задачи, так что каталог задачи не растёт бесконечно;
предыдущие `answer.json` при `--force-import` уезжают в `history/` (последние 3).

`screenshot.png` — единственный артефакт, который нельзя обезличить: это
картинка страницы, и на ней может быть ваша переписка, сайдбар и чип аккаунта.
`.hybrid/` в `.gitignore` и никуда не отправляется, но обращайтесь с этим файлом
как со скриншотом переписки. По той же причине `--artifacts-dir` не может
указывать внутрь проекта вне `.hybrid/`: иначе один `git add` — и содержимое
страницы в репозитории.

## Совместимость с живым сайтом

### Профили сайтов и DeepSeek

Автоматизация выбирает профиль из `--provider` или hostname URL. Профиль
ChatGPT содержит прежние селекторы и UI-команды; `chatgpt_ui.py` оставлен как
совместимый реэкспорт для старых инструментов. Реестры и JavaScript пробников
отдельны для каждого сайта и кэшируются по профилю.

Профиль DeepSeek зарегистрирован, но его селекторы намеренно не заполнены:
текущий `chat.deepseek.com` в доступной Chrome-сессии показывал Cloudflare
Turnstile (`#cf-turnstile`), а завершённая беседа и работающий composer не были
доступны для измерений. Автоматизация на таком профиле отказывается вводить
текст. CAPTCHA не решается движком. После ручного прохождения challenge
повторите:

```powershell
python tools/inspect_live_dom.py "https://chat.deepseek.com/" --site deepseek
python -m hybrid.cli browser read --url "<URL беседы>" --json
```

| Сигнал DeepSeek | Наблюдение в этой проверке | Статус |
|---|---|---|
| `document.title` | `DeepSeek` | снят |
| Challenge overlay | `#cf-turnstile` присутствует | обнаруживается и блокирует automation |
| Composer / send / stop | недоступны за challenge | селекторы не назначены |
| Assistant message / answer body / message key | существующей беседы нет | селекторы не назначены |
| URL беседы, локализованные подписи и роль, конец генерации | не наблюдались | не подтверждены |
| Effort / mode tabs / archive | не наблюдались | capabilities выключены |

`hybrid browser chat --provider deepseek_web` выбирает DeepSeek и его стартовый
URL, но сейчас завершится до ввода текста с сообщением, что нет live-verified
селекторов. Не отправляйте пробный prompt для «проверки»: сначала требуется
доступная страница, чтобы снять DOM и подтвердить точность селекторов.

Инспектор `tools/inspect_live_dom.py --site deepseek` печатает структуру
кандидатных узлов с длиной текста и первыми 60 символами; `--site` принимает
также `chatgpt`. Smoke-инструмент принимает тот же параметр, но отказывается
запускать синтетическую автоматизацию, если профиль ещё не подтверждён.

Реестр селекторов — это данные, а не догадки, но сайт меняется без
предупреждения. Ниже — результат проверки на живом ChatGPT (сборка с Canvas,
`data-codex-*`, CSS-module классы; залогиненный Plus-аккаунт) и то, что из этого
следует.

| Что искали | На живом сайте |
|---|---|
| `#prompt-textarea` | **исчез** (0) |
| composer | `div.ProseMirror[contenteditable='true']`, placeholder «Спросить ChatGPT» |
| `div[contenteditable="true"]` (старый fallback) | **ловит редактор кода Canvas** (`cm-content`), 4 штуки на странице |
| `button[data-testid="send-button"]` | **исчез**; кнопка появляется только при непустом composer как `button[aria-label="Отправить"][type=submit]` — реестр её ловит через `aria-label*="Отправ"` |
| `button[data-testid="stop-button"]` | **исчез** (0) |
| `[data-message-author-role]`, `.markdown`, `article`, `[data-testid^="conversation-turn"]` | **исчезли** (0) |
| реплика ассистента | `[data-talvt-turn-state]` — контейнер ответа с явным состоянием генерации |
| ключ сообщения | `[data-turn-key]` (UUID), `[data-dil-message-id]` |
| содержимое ответа | `[data-dil-message-id]` |

Что из этого закрыто в коде:

- **composer** резолвится через реестр (`#prompt-textarea` → `.ProseMirror` →
  `textarea` → общий `div[contenteditable="true"]:not(.cm-content)`), а не
  жёстким `querySelector`. Раньше `FOCUS_JS`/`CLEAR_JS`/`SUBMIT_JS` искали
  элемент сами и на этой сборке попали бы в редактор кода — то есть `_clear()`
  и вставка prompt'а уничтожили бы код в Canvas-ответе;
- пробник сообщает `composerIsCodeEditor`, и вставка в такой элемент
  **запрещена**: `ensure_ready()` падает до ввода текста;
- **реплика ассистента** находится по `[data-talvt-turn-state]`, ключ — по
  `data-turn-key` / `data-dil-message-id`;
- **конец генерации** подтверждается явным состоянием реплики (`complete`), а не
  только исчезновением кнопки Stop. Это точнее любой эвристики: пауза
  reasoning-модели больше не выглядит как завершённый ответ. Если сборка
  состояния не сообщает, работает прежнее правило (Stop видели и он исчез), а
  иначе ответ помечается `complete=false`.

Проверено живьём: `hybrid browser read --json` на реальной беседе даёт
`assistants=1 last=16350 turn=complete`, `assistant_message: found by
[data-talvt-turn-state]`, а dry-run (текст в composer без отправки) — `composer
0 → 36 chars`, `prompt_landed: true`, затем пустой composer.

Порядок действий, когда сайт снова разойдётся с реестром:

```bash
python tools/inspect_live_dom.py https://chatgpt.com/c/<id>   # что реально в DOM
hybrid browser read --json                                    # selector_report
# затем поправить SELECTORS в hybrid/browser_bridge/browser_state.py
.venv/Scripts/python -m pytest tests/ -q                      # регрессия
python tools/smoke_browser_state.py                           # живой DOM, но fake-страница
```

## Провайдеры

| Имя | Сайт | Режим |
|---|---|---|
| `deepseek_web` (алиас `deepseek`) | https://chat.deepseek.com | relay |
| `chatgpt_web` (алиас `chatgpt`) | https://chatgpt.com | relay |

Оба используют один и тот же код: Prompt Builder, Context Pack, Skills,
Session Store, Response Importer, Patch Validator, Quality Gate, Review/Apply.
Отличаются только ссылка и подсказки пользователю.

## Что делает движок с ответом

1. Разбирает секции `## SUMMARY / ## FILES / ## PATCH / ## CHECKS / ## LIMITATIONS`.
2. Если блока `diff` нет — сохраняет ответ как **анализ**, ничего не применяет.
3. Если патч есть — проверяет формат, пути (`.env`, `.hybrid/`, `config/secrets/*`,
   `tests/protected/*`, выход за пределы проекта запрещены).
4. Прогоняет патч в изолированной временной копии: `git apply`, `git diff --check`,
   `php -l` и `node --check` для изменённых файлов.
5. Показывает diff и отчёт. Применение — только `hybrid apply <TASK-ID> --yes`.

## Хранение

```
.hybrid/
  browser-tasks/
    BTASK-XXXXXXXX/
      metadata.json    # состояние задачи + prompt_sha256, prompt_source, conversation_url
      prompt.md        # подготовленный запрос
      response.md      # импортированный ответ
      review.json      # результат проверки
  tasks/
    TASK-XXXXXXXX/
      browser/         # артефакты автоматизации: state.json, timing.json, prompt.json,
                       # answer.json, screenshot.png, обезличенный dom-snippet.html

  tasks.json
```

`prompt_sha256` / `prompt_source` / `conversation_url` записываются в задачу
**только при принятом импорте**, поэтому отклонённый или упавший прогон не может
переписать происхождение уже проверенного результата.

Что движок читает и чего не читает:

| Данные | Читается | Хранится |
|---|---|---|
| Cookies, localStorage, пароли, профиль браузера | нет | нет |
| `document.body.textContent` (для login wall / CAPTCHA / лимита) | да, только **полным** пробником: один раз в секунду при ожидании composer и при разборе ошибки, максимум 4000 символов | нет — в артефакты не попадает |
| Текст ответа | да | да, `response.md` (это и есть результат) |
| Текст черновика в composer | только длина, первые 60 и последние 40 символов | `state.json` |
| DOM | обезличенный skeleton | `dom-snippet.html` |
| URL и заголовок страницы | да | в диагностике обезличены; полный URL беседы — только в `answer.json` / `metadata.json` |
| Пиксели страницы | да | `screenshot.png` при падении |

Во время самого ожидания ответа (опрос каждые 150 мс) текст страницы **не
читается вообще**: `signals_checked=false`, и такой пробник не имеет права
утверждать «login wall нет».

## Ограничения (честно)

- Это **не** автономная API-интеграция: без `--send` ничего не отправляется, а
  между сессиями ChatGPT может изменить вёрстку — тогда сработает registry
  fallback или тест `tests/test_webchat_automation.py` на fake-странице.
- Программа не обходит CAPTCHA и лимиты: при их появлении она останавливается и
  сохраняет артефакты, а не пытается пробиться.
- Какая модель доступна в веб-чате — решает ваш аккаунт; `tools/chatgpt_*.py`
  помогают посмотреть и выставить режим, но не гарантируют модель.
- `php -l` требует установленного PHP; если его нет, проверка помечается как SKIP.
- Защита артефактов — это редактирование DOM, а не криптография: `screenshot.png`
  содержит пиксели страницы, включая переписку, и его нельзя обезличить.
- Общего лимита на размер `.hybrid/` нет: файлы ограничены по содержимому и
  перезаписываются на каждый прогон одной задачи, но задач может быть много.

## Что делать при login wall / CAPTCHA / лимите

Прогон останавливается **до** ввода текста, печатает стадию и сохраняет
артефакты. Дальше:

| Состояние | Что делать |
|---|---|
| `not signed in` | `hybrid browser launch`, войти в открывшемся окне, затем `hybrid browser status` |
| `human-verification challenge` | решить её руками в том же окне; движок в неё не лезет |
| `the site reports a usage limit` | подождать лимит; повторить позже |
| `no message composer found` | страница не догрузилась: `hybrid browser read --json` покажет, что нашлось |
| `the send button was not available` | `hybrid browser read --json` → `selector_report` покажет, чем найден (или не найден) каждый элемент |

## Тесты без браузера

`tests/test_webchat_automation.py` гоняет всю state machine на fake-странице:
нет composer, login wall, captcha, disabled send + артефакты, успешный ответ,
стрим, пауза в стриме, старый ответ, таймаут до старта ответа, частичный ответ,
chunked-вставка, целостность prompt'а, `--new-conversation`, провенанс,
`--force-import`, `--allow-partial`, `--artifacts-dir` и обезличивание
артефактов. Реальный DOM для этих тестов не нужен.

`tests/test_cdp_websocket.py` проверяет кадрирование WebSocket (RFC6455):
фрагментированное сообщение собирается, ping не съедает ответ, а битый кадр
превращается в `CdpError`, а не в голый `JSONDecodeError`.

Живой DOM проверяется отдельно и вручную:

```bash
python tools/smoke_browser_state.py    # headless Chrome, fake-страница, проверка
                                       # пробника, обезличивания DOM и полного ask()
```

## Повторный импорт

Повторный импорт того же ответа отклоняется. Заменить уже проверенный результат
можно только явно: `hybrid browser import <BTASK-ID> --file answer.md --force`.
В этом случае предыдущие проверки сбрасываются, а в отчёт добавляется предупреждение.

Для `hybrid browser chat` аналог — `--force-import`; предыдущий `answer.json`
при этом не теряется, а уезжает в `browser/history/`.
