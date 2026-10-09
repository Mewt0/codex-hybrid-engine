# ТЗ: браузерная автоматизация DeepSeek Web (chat.deepseek.com)

Заказчик: владелец репозитория `F:\codex-hybrid-engine`.
Исполнитель: нейросеть-агент с доступом к репозиторию и к запущенному Chrome.
Язык кода и комментариев: английский. Язык ответа-отчёта: русский или английский.

---

# 0. Задача

Сейчас браузерная автоматизация умеет работать **только с ChatGPT**:
`chat.deepseek.com` присутствует в движке лишь как режим ручного relay
(`hybrid/browser_bridge/providers/deepseek_web.py`), без селекторов и без
state machine.

Нужно:

1. Сделать слой браузерной автоматизации **сайт-независимым** через абстракцию
   `SiteProfile`, не сломав поведение ChatGPT.
2. Вывести **живой профиль DeepSeek** (`chat.deepseek.com`) по реальному DOM —
   не по догадкам и не по памяти модели.
3. Довести `hybrid browser chat` до работы с DeepSeek: вставка промпта →
   отправка → ожидание нового ответа → извлечение → импорт.
4. Покрыть это тестами и живой проверкой.

**Главный критерий:** `hybrid browser chat --provider deepseek_web` на реальном
залогиненном `chat.deepseek.com` возвращает **текст ответа DeepSeek**, а не
промпт, не пустоту и не текст чужого сообщения.

---

# 1. Текущее состояние (проверенные факты)

## 1.1 Что уже есть и работает для ChatGPT

| Файл | Роль |
|---|---|
| `hybrid/browser_bridge/browser_state.py` | реестр селекторов `SELECTORS`, генерация JS-пробников, `PageState`, `PageStateReader`, `RunTrace`, запись артефактов |
| `hybrid/browser_bridge/webchat.py` | state machine `WebChatAutomation` |
| `hybrid/browser_bridge/chatgpt_ui.py` | режим/модель/effort, `new_conversation`, `archive_conversation` |
| `hybrid/browser_bridge/cdp.py` | stdlib CDP + WebSocket |
| `hybrid/cli.py` | команды `browser chat/read/say/at/launch/status` |
| `tests/test_webchat_automation.py` | 60+ тестов на fake-странице |
| `tools/inspect_live_dom.py` | вывод реального DOM для поддержки селекторов |
| `tools/smoke_browser_state.py` | живой прогон на headless Chrome с поддельной страницей |

Реестр селекторов хранится **глобально** в `browser_state.py`:

```python
SELECTORS: dict[str, tuple[Selector, ...]] = {
    "composer": (...),
    "send_button": (...),
    "stop_button": (...),
    "assistant_message": (...),
    "answer_body": (...),
    "new_chat": (...),
    "mode_tab": (...),
    "model_picker": (...),
    "menu_item": (...),
    "turn_state": (...),
    "message_key": (...),
}
```

Формат JS-реестра: `name -> [[query, confidence], ...]` (это важно, менять нельзя).

## 1.2 Полный список мест, зашитых под ChatGPT

Это и есть объём рефакторинга.

**`hybrid/browser_bridge/browser_state.py`**
- `SELECTORS` — все селекторы ChatGPT.
- `TURN_STATE_ATTRIBUTE = "data-talvt-turn-state"`, `TURN_STATE_DONE`, `TURN_STATE_RUNNING`.
- `STATE_JS`, `STATE_FAST_JS`, `ANSWER_JS`, `DOM_JS` — строятся из глобального реестра.
- `PageState` содержит поля, специфичные для ChatGPT (`composer_is_code_editor`, `turn_state`, `mode`, `chat_mode_available`).
- `redact_url()` знает только про ChatGPT-подобные пути.

**`hybrid/browser_bridge/webchat.py`**
- строка 30: `from . import chatgpt_ui`
- строка ~250: `chatgpt_ui.detect_effort(self.page)` в `effort_label()`
- строки 718–729: guard против метки роли, зашиты конкретные строки:
  `^(you said:|вы сказали:)` и `"ChatGPT сказал:" / "ChatGPT said:"`

**`hybrid/browser_bridge/chatgpt_ui.py`** — целиком ChatGPT:
`detect_mode`, `ensure_chat_mode`, `detect_model_picker`, `open_model_menu`,
`select_best_model`, `detect_effort`, `set_effort_max`, `diagnose_ui`,
`new_conversation(base_url="https://chatgpt.com/")`,
`archive_conversation()` с проверкой `hostname != "chatgpt.com"`.

**`hybrid/cli.py`**
- `browser_at/--url` default `https://chatgpt.com/` (строка 79)
- `browser_say/--url` default `https://chatgpt.com/` (83)
- `browser_chat/--url` default `https://chatgpt.com/` (90)
- `browser_chat/--provider` default `chatgpt_web` (93)
- `_is_new_chat_url` / валидация `--new-conversation` требуют `chatgpt.com` (865–871)
- флаг `--keep-conversation` и тексты предупреждений говорят про ChatGPT (109, 825–838)

**`hybrid/browser_bridge/session_live.py:58`** и **`hybrid/config.py:46`** —
`start_url: "https://chatgpt.com/"`.

## 1.3 Прочее важное

- `DeepSeekWebProvider` (`providers/deepseek_web.py`): `name="deepseek_web"`,
  `display_name="DeepSeek Web"`, `url="https://chat.deepseek.com"`, `mode="relay"`.
- Алиасы провайдеров — `hybrid/browser_bridge/providers/__init__.py`
  (`get_provider`, `provider_names`).
- В дереве есть незакоммиченные правки других агентов
  (`hybrid/context/repo_map.py`, `hybrid/integrations/codex_cli_delegate.py` и др.).
  **Их трогать нельзя.**

---

# 2. Целевая архитектура

## 2.1 Ввести `SiteProfile`

Новый модуль `hybrid/browser_bridge/sites/__init__.py`:

```python
@dataclass(frozen=True)
class SiteProfile:
    name: str                      # "chatgpt" | "deepseek"
    display_name: str
    hostnames: tuple[str, ...]     # ("chat.deepseek.com",) — для выбора по URL
    new_conversation_url: str
    conversation_url_re: re.Pattern[str]
    selectors: dict[str, tuple[Selector, ...]]
    # Опциональные возможности: если False, соответствующая логика пропускается,
    # а не падает.
    supports_turn_state: bool = False
    supports_effort: bool = False
    supports_mode_tabs: bool = False
    supports_archive: bool = False
    turn_state_attribute: str = ""
    turn_state_done: frozenset[str] = frozenset()
    turn_state_running: frozenset[str] = frozenset()
    # Тексты метки роли, по которым запрещено возвращать "ответ"
    role_labels: tuple[str, ...] = ()
    # Подстроки/регексы сигналов блокировки (login wall, captcha, лимит)
    login_wall_re: str = ""
    captcha_re: str = ""
    rate_limit_re: str = ""
    answer_body_join: str = "\n"   # как склеивать несколько блоков ответа
```

Модуль реестра:

```python
SITES: dict[str, SiteProfile] = {"chatgpt": CHATGPT, "deepseek": DEEPSEEK}

def site_for_provider(provider: str) -> SiteProfile: ...   # "deepseek_web" -> DEEPSEEK
def site_for_url(url: str) -> SiteProfile | None: ...      # по hostname
def default_site() -> SiteProfile: ...                     # CHATGPT (обратная совместимость)
```

## 2.2 Перенести ChatGPT в `sites/chatgpt.py`

Механический перенос без изменения поведения:

- `SELECTORS` → `CHATGPT.selectors`
- `TURN_STATE_ATTRIBUTE/DONE/RUNNING` → поля профиля
- содержимое `chatgpt_ui.py` → `sites/chatgpt.py`
- `chatgpt_ui.py` оставить как тонкий re-export на один релиз:
  `from .sites.chatgpt import *` — чтобы не ломать `tools/chatgpt_*.py` и
  `tests/test_webchat_automation.py`.

## 2.3 Параметризовать `browser_state.py` профилем

- `_registry_js(profile)` и построение `STATE_JS/STATE_FAST_JS/ANSWER_JS/DOM_JS`
  **на профиль**, с кэшем (`functools.lru_cache`) — JS собирается один раз.
- `PageStateReader(page, profile: SiteProfile = default_site(), ...)`.
- `PageState` — оставить прежние поля, но заполнять их из профиля; поля, которых
  у сайта нет, остаются `False`/`None`/`0`, и это **не** ошибка.
- `redact_url()` — оставить общим, но проверять `conversation_url_re` профиля.
- `composer_is_code_editor` — сделать общим правилом (см. п. 4.4): профиль может
  задать список классов-исключений (`exclude_classes=("cm-content", "cm-editor")`).

## 2.4 Параметризовать `webchat.py`

- `WebChatAutomation(page, reader=None, profile=None, ...)`; профиль берётся из
  `reader.profile`, если не задан.
- Убрать `from . import chatgpt_ui`. Вместо `effort_label()`:
  ```python
  def effort_label(self):
      if not self.profile.supports_effort:
          return None
      try:
          return self.profile.detect_effort(self.page)   # или отдельная функция в модуле сайта
      except CdpError as exc:
          self.trace.note(...); return None
  ```
- Guard метки роли — из профиля:
  ```python
  if any(label.lower() in text.lower() for label in self.profile.role_labels):
      raise WebChatError("the selected assistant message contains a role label; refusing ...")
  ```
  Плюс обобщить уже существующий регекс `^(you said:|вы сказали:)` до
  `profile.role_labels` + общий шаблон «<метка> ... сказал/you said».

## 2.5 CLI и конфиг

- `hybrid/cli.py`: `--provider` определяет и провайдера, и сайт, и дефолтный URL:
  ```python
  profile = site_for_provider(args.provider)
  target_url = args.continue_url or args.url or profile.new_conversation_url
  ```
  Дефолт `--url` менять на `None`, а не на конкретный сайт.
- Валидация `--new-conversation` — по `profile.conversation_url_re` и
  `profile.new_conversation_url`, без хардкода `chatgpt.com`.
- `--keep-conversation` / архивация — только если `profile.supports_archive`;
  иначе флаг либо игнорируется с явным сообщением, либо не регистрируется.
- `browser_session.start_url` в `config.py` — оставить дефолт, но сессия не
  должна навязывать ChatGPT при работе с DeepSeek.

---

# 3. Что именно вывести для DeepSeek (главная работа)

**Категорически нельзя** придумывать селекторы. Их надо **снять с живого DOM**
`chat.deepseek.com` в залогиненном профиле. Ниже — что снять и как.

## 3.1 Профиль DeepSeek должен определить

| Поле | Что это | Обязательность |
|---|---|---|
| `composer` | поле ввода сообщения (textarea или contenteditable) | обязательно |
| `send_button` | кнопка отправки (может появляться только при непустом composer) | обязательно |
| `stop_button` | кнопка остановки генерации | обязательно проверить; если её нет — `supports_turn_state` или иной признак конца |
| `assistant_message` | контейнер **только** ответа ассистента | обязательно |
| `answer_body` | узел с текстом ответа внутри сообщения | обязательно |
| `message_key` | атрибут-идентификатор сообщения | желательно |
| `turn_state` | атрибут состояния генерации, если есть | желательно (см. п. 4.7) |
| `new_chat` | кнопка/ссылка нового чата | для `--new-conversation` |
| `conversation_url_re` | шаблон URL одной беседы | обязательно |
| `login_wall_re`, `captcha_re`, `rate_limit_re` | сигналы блокировки по тексту | обязательно |
| `role_labels` | строки вида «DeepSeek said:», «Вы сказали:» | обязательно |
| `supports_effort`, `supports_mode_tabs`, `supports_archive` | есть ли аналог | определить и честно проставить |

## 3.2 Процедура снятия (обязательная последовательность)

Сессия Chrome уже поднята: порт `9333`, профиль
`F:\codex-hybrid-engine\.hybrid\browser-profile`, там же живёт логин.

**Шаг 1.** Убедиться, что сессия жива:
```powershell
cd F:\codex-hybrid-engine
.\.venv\Scripts\python.exe -m hybrid.cli browser status
```

**Шаг 2.** Открыть DeepSeek и снять общие сигналы:
```powershell
.\.venv\Scripts\python.exe tools\inspect_live_dom.py "https://chat.deepseek.com/"
```
Скрипт печатает: счётчики по кандидатам, **все** `data-*` атрибуты страницы,
видимые подписи кнопок, и текущий `selector_report`. Это основной инструмент.

**Шаг 3.** Залогиниться руками в открывшемся окне, если требуется, и повторить
шаг 2.

**Шаг 4.** Отправить руками короткий пробный промпт (например `Reply with the
single word: PONG`) и **во время генерации** снять состояние:
```powershell
.\.venv\Scripts\python.exe -m hybrid.cli browser read --json
```
Зафиксировать, что меняется: появляется/исчезает кнопка остановки, какие узлы
добавляются, есть ли атрибут состояния.

**Шаг 5.** После завершения генерации снять структуру ещё раз, затем вывести
структуру контейнера ответа. Для этого написать одноразовый пробник
(временный файл вне репозитория допустим) по образцу:

```python
"""Print the structure of the node we believe is the assistant message."""
PROBE = """
(() => {
  const brief = (n) => ({
    tag: n.tagName.toLowerCase(),
    attrs: Object.fromEntries(Array.from(n.attributes).map((a) => [a.name, a.value.slice(0, 40)])),
    cls: (typeof n.className === 'string' ? n.className : '').split(/\\s+/).slice(0, 4).join(' '),
    kids: n.children.length,
    textLen: (n.textContent || '').length,
    head: (n.textContent || '').trim().slice(0, 60).replace(/\\s+/g, ' '),
  });
  const out = [];
  document.querySelectorAll('div, section, article, main').forEach((n) => {
    const t = (n.textContent || '').trim();
    if (t.length < 200) return;
    out.push(brief(n));
  });
  return { candidates: out.slice(0, 30) };
})()
"""
```

**Шаг 6.** Проверить каждый выведенный селектор **по отдельности** и записать
в отчёт: `селектор → сколько совпадений → textLength → первые 60 символов`.
Селектор принимается, только если он:
- находит ровно один узел на сообщение и не находит узел пользователя;
- его `textContent` начинается с текста ответа, а не с промпта.

**Шаг 7.** Заполнить `DEEPSEEK` этими селекторами и прогнать живую проверку из
раздела 7.

## 3.3 Стартовые гипотезы (проверить, НЕ считать фактом)

Это направления поиска, а не утверждения:

- сайт — React SPA, поэтому `document.readyState === 'complete'` наступит
  **раньше**, чем смонтируется приложение (см. п. 4.3);
- composer, вероятно, `textarea` либо `div[contenteditable]` с `role="textbox"`;
- у DeepSeek есть переключатели режимов («DeepThink» / R1, «Search») — проверить,
  влияют ли они на разметку и нужно ли их учитывать в `supports_mode_tabs`;
- кнопка остановки, вероятно, появляется только во время генерации;
- URL беседы, вероятно, содержит идентификатор вида `/a/chat/s/<id>` или
  `/chat/<id>` — снять точный шаблон и записать в `conversation_url_re`;
- атрибут состояния генерации может отсутствовать — тогда опираться на кнопку
  остановки и на правило из п. 4.7.

---

# 4. Ловушки (все получены эмпирически на ChatGPT — повторять их нельзя)

Это самая важная часть ТЗ. Каждая ловушка уже стоила отладки.

### 4.1 «Turn wrapper» ≠ сообщение ассистента

**Что произошло.** Селектор `[data-talvt-turn-state]` выглядел как «ответ
ассистента», а на деле матчил обёртку всей пары реплик:

```
div[data-talvt-turn-state]                         textLen 23750
├── div[data-user-message-bubble]   ← ПРОМПТ        textLen  6886
├── h4[data-conversation-role=assistant] «ChatGPT сказал:»   15
└── div[data-dil-message-id]        ← ОТВЕТ         textLen 16838
```

Извлекался промпт (6912 символов) вместо ответа (16838).

**Требование.** Прежде чем принимать селектор за «сообщение ассистента»,
измерить:
- `textLen` самого узла,
- `textLen` каждого дочернего «сообщения» внутри него,
- `textHead` узла и детей.

Если `textHead` узла начинается с метки пользователя — узел брать нельзя.
В отчёт обязательно вложить это измерение.

### 4.2 Атрибут, названный «turn/message», может не означать роль

`data-turn-key`, `data-content-search-turn-key`, `data-conversation-role` — все
встречались, и только последний реально говорит о роли, да и то на служебном
`<h4 class="sr-only">`. Роль надо подтверждать структурой (наличие панели
действий рядом, отсутствие пользовательского «пузыря» внутри).

### 4.3 `readyState === 'complete'` ≠ приложение смонтировано

Замер на живом ChatGPT: сразу после навигации страница отдаёт
`composer: found by textarea`, `assistant messages: 0` — это оболочка без
приложения. Через пару секунд та же беседа: `composer by div.ProseMirror`,
`assistants=1 last=16350`.

**Требование.** Готовность страницы определять по **уверенности селектора**
(`composer_confidence >= 0.8`), а не по «что-то нашлось». Именно так сделано в
`PageStateReader.wait_ready` (`browser_state.py:760`). Не заменять это на
`time.sleep`.

### 4.4 Общий `div[contenteditable="true"]` может оказаться редактором кода

На беседе с Canvas этот селектор нашёл **CodeMirror** (`class="cm-content"`,
placeholder «Редактировать код», 4 штуки на странице), а не composer.
`_clear()` и вставка промпта уничтожили бы код пользователя.

**Требование.** Профиль задаёт `exclude_classes`; пробник сообщает
`composerIsCodeEditor`; `ensure_ready()` обязан **отказаться** печатать в такой
узел. Для DeepSeek проверить, нет ли на странице своих contenteditable
(например, редактор кода в ответе) — и если есть, внести их классы в исключения.

### 4.5 `data-testid` исчезают между сборками

На текущем ChatGPT **исчезли**: `#prompt-textarea`,
`button[data-testid="send-button"]`, `button[data-testid="stop-button"]`,
`[data-message-author-role]`, `.markdown`, `article`,
`[data-testid^="conversation-turn"]`.

**Требование.** У каждого элемента — минимум 3 селектора с разной уверенностью,
и обязательные fallback'и по `aria-label` (в двух языках) и по `role`. Проверить
на DeepSeek, что запасные селекторы реально находятся при пустом и непустом
composer.

### 4.6 Кнопка Stop появляется раньше узла ответа — и это не «новый ответ»

На новом чате кнопка остановки возникла раньше, чем контейнер ответа. Логика
«увидели Stop → значит ответ появился» зафиксировала **пустой ключ сообщения**, и
прогон умер на готовом ответе в 23 750 символов:

```
ERROR: browser automation failed at stage FAILED: no assistant message was identified to read.
```

**Требование.** Подтверждение отправки (`_accepted`) и подтверждение появления
**читаемого** сообщения (`_new_message`) — разные предикаты. `_new_message`
обязан требовать непустой ключ сообщения. Для DeepSeek специально проверить
порядок появления узлов.

### 4.7 «Текст перестал меняться» ≠ генерация закончилась

Reasoning-модель может думать секундами без дельты текста, а на время
веб-поиска кнопка Stop может быть не видна. Принять паузу за конец — значит
импортировать обрезанный ответ как готовый.

**Требование.** Завершение подтверждается **явно**, в порядке приоритета:
1. сайт сам сообщает состояние реплики (`complete`), — если такое поле есть;
2. кнопка Stop наблюдалась и исчезла;
3. иначе — ответ помечается `complete=false`, и CLI отказывается его
   импортировать без `--allow-partial`.

Для DeepSeek: если атрибута состояния нет — обязательно проверить, что (2)
работает, и записать в отчёт, что именно наблюдалось во время генерации.

### 4.8 Кнопка отправки может не существовать при пустом composer

Проверено: на ChatGPT send-кнопки нет, пока composer пуст; она появляется как
`button[aria-label="Отправить"][type=submit]` только с текстом.
Поэтому «не нашли send» до вставки текста — **не ошибка**.

**Требование.** `send_button` проверять **после** вставки промпта. Для DeepSeek
зафиксировать оба состояния (пусто / есть текст) в отчёте.

### 4.9 Длина — плохая проверка целостности промпта

`innerText` схлопывает пустые строки: промпт из 12 символов вернулся как 21
(+75%), а допуск 5% на промпте в 20 000 символов разрешил бы молча потерять 1000.

**Требование.** Сверять содержимое: потеря символов — ошибка; рост — нормальная
нормализация; плюс сравнение первых и последних N символов. Реализация —
`WebChatAutomation.prompt_landed` (`webchat.py:343`). Переиспользовать, не
изобретать заново.

### 4.10 В извлечённый текст попадают служебные метки роли

В сохранённом «ответе» оказалось `ChatGPT сказал:` / `Вы сказали:`.

**Требование.** `role_labels` профиля участвуют в guard'е, и при совпадении
извлечение **падает**, а не возвращает текст. Для DeepSeek снять реальные строки
меток (локализация!) и внести их.

### 4.11 Локализация

Аккаунт в этой среде русскоязычный: подписи кнопок приходят как «Отправить»,
«Остановить», «Скопировать сообщение». Селекторы только по английскому тексту
здесь не сработают.

**Требование.** В fallback'ах — минимум ru и en. Никогда не закладываться на
один язык. Для DeepSeek снять подписи в обеих локализациях, если возможно.

### 4.12 Артефакты не должны содержать содержимое страницы

Уже реализовано и это нельзя ломать:
- `dom-snippet.html` — **обезличенный скелет**: нет текстовых узлов, нет
  `<script>/<head>/<style>`, атрибуты только из allow-list (без `aria-label`,
  `value`, `href`); лимит 120 000 символов;
- `state.json` / `timing.json` — URL и `title` редактируются
  (`redact_url`, `title_length` вместо заголовка);
- `screenshot.png` — единственный нередактируемый артефакт, это признано честно.

**Требование для DeepSeek:** убедиться, что `document.title` на
`chat.deepseek.com` не является названием беседы, и если является — редактирование
обязательно (оно уже общее).

---

# 5. Обязательные изменения по файлам

| Файл | Что сделать |
|---|---|
| `hybrid/browser_bridge/sites/__init__.py` | **новый**: `SiteProfile`, `Selector` (перенести сюда или реэкспортировать), `SITES`, `site_for_provider`, `site_for_url`, `default_site` |
| `hybrid/browser_bridge/sites/chatgpt.py` | **новый**: перенос `SELECTORS`, `TURN_STATE_*`, содержимого `chatgpt_ui.py` |
| `hybrid/browser_bridge/sites/deepseek.py` | **новый**: профиль DeepSeek + `new_conversation`, `detect_effort` (если есть), `archive_conversation` (если есть) |
| `hybrid/browser_bridge/browser_state.py` | параметризовать профилем сборку JS и `PageStateReader`; кэшировать JS на профиль; `PageState` дополнить полем `profile` (можно строкой имени) |
| `hybrid/browser_bridge/webchat.py` | убрать импорт `chatgpt_ui`; брать профиль из reader; guard меток роли из профиля |
| `hybrid/browser_bridge/chatgpt_ui.py` | оставить тонким реэкспортом `sites/chatgpt.py` (совместимость `tools/chatgpt_*.py`) |
| `hybrid/cli.py` | `--url` дефолт убрать; `--provider` управляет сайтом; валидация `--new-conversation` и архивация — через профиль |
| `hybrid/browser_bridge/providers/__init__.py` | связь `provider.name → site` (или через `site_for_provider`) |
| `tools/inspect_live_dom.py` | принимать `--site deepseek` и печатать `selector_report` для выбранного профиля |
| `tools/smoke_browser_state.py` | принимать `--site deepseek` и подставлять профиль |
| `docs/BROWSER_BRIDGE.md` | добавить раздел про DeepSeek и таблицу «что где снято» |

**Запрещено** менять: `hybrid/context/repo_map.py`, `tests/test_repo_map.py`,
`hybrid/integrations/codex_cli_delegate.py`, `tests/test_harness_adapter.py`
(работа других агентов).

---

# 6. Тесты

## 6.1 Fake-страница должна стать профильной

`tests/test_webchat_automation.py` содержит `FakePage`, который отвечает на
JS-маркеры `/*hybrid:...*/`. Требуется:

- `FakePage` принимает профиль и отвечает на маркеры любого профиля;
- существующие 60+ тестов **остаются зелёными** и, где возможно,
  **параметризуются** по профилям: `@pytest.mark.parametrize("site", ["chatgpt", "deepseek"])`.

## 6.2 Новые обязательные тесты

`tests/test_deepseek_profile.py`:

1. профиль DeepSeek зарегистрирован и находится по `provider_name` и по hostname;
2. у каждого обязательного селектора есть ≥2 fallback'а (проверка структуры реестра);
3. `role_labels` DeepSeek непусты, и `_extract` падает на тексте с меткой;
4. `answer_body` не может вернуть текст пользовательского «пузыря» — на fake-странице
   с двумя сообщениями извлекается только ответ;
5. если `supports_turn_state is False`, завершение определяется исчезновением
   Stop; если Stop не наблюдался — `complete=False` и CLI отказывает;
6. `new_conversation` для DeepSeek проверяет пустоту composer'а;
7. `composer_is_code_editor` блокирует вставку;
8. guard «prompt не влез целиком» работает на промпте с пустыми строками.

`tests/test_site_profiles.py`:

9. профили не делят мутабельное состояние (реестр селекторов не общий объект);
10. `site_for_url("https://chat.deepseek.com/a/chat/s/...")` возвращает DeepSeek,
    `site_for_url("https://chatgpt.com/c/...")` — ChatGPT, чужой домен — `None`;
11. переключение профиля не меняет сгенерированный JS другого профиля (кэш не
    путает ключи).

## 6.3 Регрессия ChatGPT

Полный прогон `pytest -q` должен быть зелёным. Отдельно проверить:

```powershell
.\.venv\Scripts\python.exe -m hybrid.cli browser read --json
```

на уже открытой ChatGPT-беседе — `selector_report` не должен измениться по
сравнению с текущим поведением (снять «до» и «после»).

---

# 7. Живая проверка (acceptance)

Обязательна, иначе работа не принимается.

**A. Профиль снят верно.** На живом `chat.deepseek.com`:

```powershell
.\.venv\Scripts\python.exe tools\inspect_live_dom.py "https://chat.deepseek.com/" --site deepseek
```

В отчёт вложить вывод целиком.

**B. Чтение существующей беседы.** Открыть беседу DeepSeek с известным ответом:

```powershell
.\.venv\Scripts\python.exe -m hybrid.cli browser read `
  --url "<URL беседы DeepSeek>" --json
```

Критерии:
- `composer: found by ...` — селектор с уверенностью ≥ 0.8;
- `assistant_message: found by ...`;
- `assistant_count ≥ 1`;
- извлечённый текст начинается с содержательного ответа и **не содержит**
  `role_labels` и текста промпта;
- длина извлечённого текста согласуется с `textLen` узла ответа.

**C. Полный цикл, без «сжигания» лишнего.** Явно **не** отправлять сообщение,
если заказчик не разрешил. Достаточно:

```powershell
# dry-run: промпт попадает в composer и НЕ отправляется
.\.venv\Scripts\python.exe -m hybrid.cli browser chat `
  --provider deepseek_web --file <prompt.md> --new-conversation
```

Критерии: `--new-conversation` открыл пустой чат; текст вставился; проверка
целостности прошла; composer очищен; ничего не отправлено.

**D. Отправка (только с явного разрешения).**

```powershell
.\.venv\Scripts\python.exe -m hybrid.cli browser chat `
  --provider deepseek_web --file <prompt.md> --send --new-conversation --timeout 420
```

Критерии: ответ извлечён, `complete=true`, импорт не форсирован, артефакты
записаны в `.hybrid/tasks/<TASK>/browser/`.

**E. ChatGPT не сломан.** Повторить пункт B на ChatGPT-беседе.

---

# 8. Отдельный обязательный пункт: дыра в `browser_session`

Это независимый дефект безопасности, найденный при работе над этим же слоем.
Проверено экспериментально: проектный `config/settings.yaml` может задать

```yaml
browser_session:
  command: C:\Windows\System32\calc.exe
  profile_dir: C:\Windows
```

и движок это примет:

```
project-supplied browser_session.command     -> C:\Windows\System32\calc.exe
project-supplied browser_session.profile_dir -> C:\Windows
ignored_project_fields -> []          ← ничего не отброшено
```

То есть `hybrid --project <чужой проект> browser launch` запустит произвольный
исполняемый файл. Для `providers.codex.command` такая защита уже есть
(`TRUSTED_PROVIDER_FIELDS`, `hybrid/config.py:93`), а `browser_session` в неё не
входит: `_filtered_project_config` обрабатывает только `providers.*` и
`context.allowed_files`.

**Требуется:**
1. Добавить `browser_session.command` и `browser_session.profile_dir` в
   trusted-only поля (нельзя задавать из проектного конфига).
2. Запись об отброшенном поле должна попадать в
   `settings.sources["ignored_project_fields"]`.
3. Тест: проект пытается задать оба поля → значения игнорируются, поля
   перечислены в `ignored_project_fields`, движок использует `find_chrome()` и
   профиль по умолчанию.

---

# 9. Ограничения

1. **Только стандартная библиотека.** Никаких новых зависимостей. Playwright
   недоступен (`find_spec('playwright')` → `None`) и вводить его нельзя.
2. **Не ломать архитектуру состояния.** `webchat.py` — state machine с
   адаптивным опросом 150 мс / 500 мс / 1.5 с; каждый шаг — предикат с дедлайном;
   фиксированные `sleep` вместо ожидания условия не добавлять.
3. **Завершение ответа доказывается, а не угадывается.** Правило из п. 4.7
   неприкосновенно.
4. **Никакого «fallback на последнее сообщение»** в извлечении ответа.
5. **Артефакты остаются обезличенными** (п. 4.12).
6. **`--force-import` остаётся необязательным**, по умолчанию импорт не
   форсируется; `--allow-partial` нужен явно.
7. **Идемпотентность селекторов.** Если селектор не найден, движок обязан
   падать с внятным сообщением и `selector_report`, а не «догадываться».
8. **Не трогать файлы других агентов** (см. п. 5).

---

# 10. Что сдать (evidence) и определение готовности

Работа принимается только вместе с:

1. **Таблицей живых селекторов DeepSeek**: селектор → назначение →
   уверенность → сколько совпадений → `textLen` → первые 60 символов.
2. **Дампом структуры узла ответа** DeepSeek (как в п. 4.1) с доказательством,
   что узел не содержит промпт.
3. **Выводом `inspect_live_dom.py --site deepseek`** целиком.
4. **Выводом `browser read --json`** на реальной беседе DeepSeek: до и после.
5. **Выводом dry-run** `browser chat --provider deepseek_web` (без отправки).
6. **`pytest -q` целиком**, с числом тестов до и после.
7. **Списком того, что НЕ удалось проверить** и почему. Честный список
   невыполненных проверок обязателен; «всё работает» без вывода не принимается.
8. **Диффом** и коротким описанием, что перенесено, что добавлено.

Определение готовности:

- [ ] ChatGPT работает как раньше (регрессия зелёная, `selector_report` не изменился)
- [ ] Профиль DeepSeek зарегистрирован, обязательные селекторы заполнены живыми данными
- [ ] `browser read` на реальной беседе DeepSeek возвращает ответ, не промпт
- [ ] guard меток роли работает для обоих сайтов
- [ ] тесты профильные и параметризованные, все зелёные
- [ ] дыра `browser_session.command` закрыта и покрыта тестом
- [ ] документация обновлена

---

# 11. Чего делать НЕ надо

- Не строить новый движок рядом со старым. Нужен профиль, а не второй `webchat.py`.
- Не хардкодить селекторы «по памяти» о DeepSeek и не брать их из интернета —
  только измерение на живом DOM.
- Не добавлять Playwright, Selenium, jsdom.
- Не отправлять сообщения в аккаунт без явного разрешения заказчика.
- Не «упрощать» guard'ы (метки роли, целостность промпта, обязательность
  доказательства завершения) ради зелёных тестов.
- Не менять файлы других агентов.
- Не удалять и не переименовывать `tools/chatgpt_*.py` — на них ссылается
  документация.
