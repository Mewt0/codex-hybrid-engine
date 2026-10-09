# ЗАДАНИЕ: Browser AI Bridge для Codex Hybrid Engine

Ты — senior Python-разработчик. Нужно написать **готовый к вставке код** нескольких модулей
для существующего проекта. Не переписывай существующие подсистемы, не добавляй
зависимостей, не вызывай платные API.

## 1. Что это за проект

`Codex Hybrid Engine` — локальный Python-CLI, который маршрутизирует задачи разработки
между сильным агентом (Codex CLI) и дешёвыми OpenAI-совместимыми моделями. Уже есть:
Task Controller, атомарное JSON-хранилище задач, Git-worktree изоляция, quality-гейты,
review/apply с явным подтверждением, Unified Skills Layer, Design Memory, Context Pack.

Мы добавляем **Browser AI Bridge**: провайдеры, которые работают через **официальный
веб-чат** сильной модели, когда API-ключа нет. Это режим **с участием пользователя
(relay)**: движок готовит запрос → пользователь сам открывает сайт, сам входит в свой
аккаунт, сам отправляет запрос и сам возвращает ответ в движок. Никакого скрапинга,
перехвата внутренних API, обхода CAPTCHA/лимитов и чтения cookies.

## 2. Жёсткие ограничения

- Только стандартная библиотека Python 3.11+. Никаких новых зависимостей.
- Не читать и не хранить cookies, токены, пароли, данные профиля браузера.
- Не делать сетевых запросов к сайтам ИИ из кода. Единственное сетевое действие —
  открыть URL в системном браузере пользователя.
- Не выполнять shell-команды, которые «предлагает» ответ модели.
- Секреты и `.env` не попадают в контекст никогда.
- Патчи пишутся только с LF (`newline="\n"`), иначе `git apply --cached` падает на Windows.
- Стиль: `from __future__ import annotations`, type hints, dataclasses, без глобального
  состояния, ошибки — через собственные исключения.

## 3. Что уже существует (использовать, не дублировать)

```python
# hybrid/tasks.py
class TaskRecord:  # поля, которые тебе нужны
    task_id: str
    description: str
    mode: str
    provider: str
    status: str          # planned|running|waiting_for_user|ready_for_review|applied|failed
    artifact_dir: str | None
    patch_sha256: str | None
    changed_files: list[str]
    checks: dict
    profile: str | None
    source: str | None
    prompt_path: str | None
    response_path: str | None
    import_count: int
    analysis: str | None
    skills: list[str]
    @staticmethod
    def new(description, mode, provider, complexity, project_dir) -> "TaskRecord": ...
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "TaskRecord": ...

# hybrid/context/__init__.py
@dataclass
class Skill:
    name: str; description: str; triggers: list[str]; body: str; path: Path | None

@dataclass
class ContextPack:
    task_id: str; profile: str
    skills: list[Skill]
    sections: dict[str, str]        # ключи: "project_context", "design"
    files: list[tuple[str, str]]    # (relative_path, content)
    truncated: list[str]; missing: list[str]
    def prompt_text(self) -> str: ...
    def skill_names(self) -> list[str]: ...
    def used_files(self) -> list[str]: ...

class ContextBuilder:
    def __init__(self, settings, skill_library=None): ...
    def build(self, task, profile: str | None = None) -> ContextPack: ...
    def skills(self) -> dict[str, Skill]: ...
    def profiles(self) -> dict[str, list[str]]: ...

def choose_profile(description: str, forced: str | None = None) -> str: ...
def render_prompt(pack: ContextPack) -> str: ...

# hybrid/context/file_context.py
def allowed_files(settings) -> list[str]: ...
def read_allowed_file(settings, rel: str) -> str | None: ...
def forbidden_patterns(settings) -> list[str]: ...
def is_forbidden(rel: str, patterns: list[str]) -> bool: ...

# hybrid/controller.py (существующий класс Controller)
class Controller:
    def __init__(self, settings): ...          # settings.raw, settings.root, settings.data_dir, self.store
    # store: StateStore с методами save(TaskRecord), get(task_id) -> TaskRecord
    def _validate_patch_on_temp(self, record: TaskRecord, patch: str) -> list[CheckResult]: ...
    def _has_fail(self, checks) -> bool: ...
    def _artifact_dir(self, task_id: str) -> Path: ...
    def _save_patch(self, record: TaskRecord, patch: str) -> Path: ...
    def apply(self, task_id: str, confirm: bool = False) -> TaskRecord: ...

# hybrid/quality/checks.py
@dataclass
class CheckResult:
    name: str; status: str; detail: str = ""

# hybrid/browser_bridge/sessions.py (УЖЕ НАПИСАН, используй как есть)
@dataclass
class BrowserTask:
    task_id: str; provider: str; description: str; profile: str; status: str
    task_mode: str = "browser"; url: str = ""
    prompt_path: str = ""; response_path: str | None = None; review_path: str | None = None
    engine_task_id: str | None = None
    skills: list[str] = field(default_factory=list)
    response_sha256: str | None = None
    import_count: int = 0
    created_at: float = 0.0; updated_at: float = 0.0
    @staticmethod
    def new(provider, description, profile, url) -> "BrowserTask": ...
    def to_dict(self) -> dict: ...

class BrowserTaskStore:
    def __init__(self, data_dir: Path): ...
    def task_dir(self, task_id) -> Path
    def prompt_file(self, task_id) -> Path
    def response_file(self, task_id) -> Path
    def review_file(self, task_id) -> Path
    def metadata_file(self, task_id) -> Path
    def all(self) -> dict[str, dict]
    def save(self, task: BrowserTask) -> BrowserTask
    def get(self, task_id: str) -> BrowserTask
    def history(self) -> list[BrowserTask]
    def cancel(self, task_id: str) -> BrowserTask
    def write_prompt(self, task_id: str, text: str) -> Path
    def read_prompt(self, task_id: str) -> str
    def import_response(self, task_id: str, text: str, force: bool = False) -> tuple[Path, str]
    def write_review(self, task_id: str, payload: dict) -> Path

class BrowserBridgeError(RuntimeError): ...
class ResponseAlreadyImported(BrowserBridgeError): ...
```

## 4. Что нужно написать

### 4.1 `hybrid/browser_bridge/providers/base.py`

```python
@dataclass(frozen=True)
class BrowserPrompt:
    text: str                    # готовый текст запроса
    provider: str
    url: str
    notes: list[str]             # подсказки пользователю по шагам

@dataclass
class BrowserReply:
    text: str
    task_id: str
    prompt: BrowserPrompt
    def prepare(self, task, context_pack) -> BrowserPrompt: ...
```

```python
class BrowserProvider(ABC):
    name: str                    # "deepseek_web" | "chatgpt_web"
    display_name: str
    url: str
    mode: str                    # "relay"
    def available(self) -> tuple[bool, str]: ...   # проверка возможности открыть URL
    def prepare(self, task, context_pack) -> BrowserPrompt: ...
    def open_url(self) -> str: ...                 # открыть в системном браузере, вернуть url
```

`open_url` обязан использовать `webbrowser.open(url)` и **не** передавать никаких
параметров, токенов и идентификаторов задачи в URL. Если открыть не удалось — вернуть
понятную ошибку, а не падать стектрейсом.

### 4.2 `hybrid/browser_bridge/providers/deepseek_web.py`

- `name = "deepseek_web"`, `url = "https://chat.deepseek.com"`.
- `notes`: «войдите в свою учётную запись», «вставьте запрос», «скопируйте ответ целиком
  и верните его командой `hybrid browser import`».
- Провайдер не проверяет и не хранит состояние аккаунта.

### 4.3 `hybrid/browser_bridge/providers/chatgpt_web.py`

- `name = "chatgpt_web"`, `url = "https://chatgpt.com"`.
- Тот же интерфейс, другая ссылка и подсказки. Отдельной архитектуры быть не должно.

### 4.4 `hybrid/browser_bridge/prompt_builder.py`

```python
class PromptBuilder:
    def __init__(self, settings, context_builder): ...
    def build(self, task, context_pack, provider) -> BrowserPrompt: ...
    def build_review(self, task, context_pack, provider, first_solution: str) -> BrowserPrompt: ...
```

В текст запроса обязательно входят:

1. Роль и цель задачи.
2. Реальный стек проекта: legacy PHP, plain JavaScript, MySQL, HTML/CSS, без фреймворков.
3. Явное предупреждение: **у тебя нет доступа к локальной файловой системе и терминалу**;
   не проси запускать команды; если нужен файл — попроси его текстом.
4. Контекст только из `context_pack` (skills + design + files).
5. Правила обратной совместимости: не менять публичные функции, не менять формат
   ответов существующих endpoint'ов, не переписывать проект.
6. Требования безопасности: параметризованный SQL, экранирование вывода, проверка прав.
7. Точный формат ответа (см. ниже).
8. Требование к тестированию: какие проверки должны проходить.

Формат ответа, который ты требуешь от модели:

```
## SUMMARY
<2-5 предложений>

## FILES
- путь/файл.php — что меняется

## PATCH
```diff
<unified diff или "нет">
```

## CHECKS
- ...

## LIMITATIONS
- ...
```

`build_review` формирует запрос независимого ревью: даёт исходную задачу, правила проекта
и первое решение, и просит найти ошибки/риски, тоже в разделённом формате
(`## VERDICT`, `## ISSUES`, `## PATCH`, `## LIMITATIONS`).

### 4.5 `hybrid/browser_bridge/response_parser.py`

```python
@dataclass
class ParsedResponse:
    task_id: str
    sections: dict[str, str]
    patch: str | None
    patch_blocks: list[str]
    files: list[str]
    response_sha256: str
    is_patch: bool
    warnings: list[str]

class ResponseParser:
    def parse(self, task_id: str, text: str) -> ParsedResponse: ...
    def validate_patch(self, parsed: ParsedResponse, settings, project_dir) -> list[CheckResult]: ...
```

Требования:

- Извлекать секции по заголовкам `## NAME` (регистр не важен), текст до первого `##` — `PREAMBLE`.
- Патч — только содержимое блока `````diff```` (или ```` ```patch ````). Если в ответе
  просто текст — `patch is None`, `is_patch = False`, всё сохраняется как «предложение/анализ».
- `warnings` заполнять, если: нет секции PATCH; несколько diff-блоков; патч не начинается
  с `diff --git`; в ответе есть текст, похожий на shell-команды, которые модель просит
  выполнить (это предупреждение, а не исполнение).
- `validate_patch` возвращает `CheckResult`-список: патч пустой/не unified/затрагивает
  запрещённый путь/выходит за пределы проекта/содержит `.hybrid/`, `.env`, `config/secrets/*`,
  `tests/protected/*`. Использовать `is_forbidden` и `forbidden_patterns` из
  `hybrid.context.file_context`, а также проверку `Path(rel).resolve()` внутри `project_dir`.
  Имена проверок: `"Response Format"`, `"Patch Format"`, `"Patch Paths"`.
- Хэш: `hashlib.sha256(text.encode("utf-8")).hexdigest()`.

### 4.6 `hybrid/browser_bridge/controller.py`

```python
class BrowserBridge:
    def __init__(self, settings, controller, store, context_builder, prompt_builder, parser): ...
    def providers(self) -> list[BrowserProvider]: ...
    def prepare(self, description: str, provider: str, profile: str | None) -> BrowserTask: ...
    def prompt(self, task_id: str) -> str: ...
    def open(self, task_id: str) -> str: ...
    def import_response(self, task_id: str, text: str, force: bool = False) -> TaskRecord: ...
    def review_payload(self, task_id: str) -> dict: ...
    def history(self) -> list[BrowserTask]: ...
    def cancel(self, task_id: str) -> BrowserTask: ...
```

Поведение `prepare`:

1. Проверить, что провайдер известен, иначе `BrowserBridgeError` со списком известных.
2. Определить профиль через `choose_profile`.
3. Создать внутренний `TaskRecord` (`TaskRecord.new(description, "browser", provider, "medium", settings.root)`),
   выставить `task.profile`, `task.source = "browser_bridge"`, `task.status = "waiting_for_user"`.
4. Собрать `ContextPack` через `context_builder.build(task, profile)`.
5. Записать `prompt.md` в артефакты задачи и в `browser-tasks/<BTASK>/prompt.md`.
6. Сохранить `TaskRecord` и `BrowserTask`, связав их через `engine_task_id`.
7. Ничего не отправлять в сеть.

Поведение `import_response`:

1. Если задача уже `ready_for_review`/`applied` и `force=False` → `ResponseAlreadyImported`.
2. Разобрать ответ `ResponseParser.parse`.
3. Если это патч: прогнать `validate_patch`; при ошибках формата/путей —
   статус `failed`, полный текст ответа и предупреждения сохраняются, патч **не** применяется.
   Если проверки прошли — записать патч как артефакт через `controller._save_patch`,
   вызвать `controller._validate_patch_on_temp`, заполнить `task.checks`, `task.changed_files`,
   статус `ready_for_review` или `failed`.
4. Если это не патч: сохранить как `analysis`, статус остаётся `waiting_for_user`
   с пометкой в `review.json`, изменения не применяются.
5. Повторный импорт при `force=True` разрешён, но обязан сбросить предыдущие проверки и
   увеличить `import_count`; в отчёт добавить предупреждение о перезаписи.
6. Записать `review.json`: статус, провайдер, профиль, skills, changed_files, checks,
   warnings, limitations, хэш ответа, был ли применён патч.

Поведение `review_payload`: собрать словарь для CLI/отчёта (без записи файлов).

## 5. Формат ответа, который ты должен вернуть

Верни **ровно** эти файлы, каждый целиком, без сокращений и без «...»:

1. `hybrid/browser_bridge/__init__.py`
2. `hybrid/browser_bridge/providers/__init__.py`
3. `hybrid/browser_bridge/providers/base.py`
4. `hybrid/browser_bridge/providers/deepseek_web.py`
5. `hybrid/browser_bridge/providers/chatgpt_web.py`
6. `hybrid/browser_bridge/prompt_builder.py`
7. `hybrid/browser_bridge/response_parser.py`
8. `hybrid/browser_bridge/controller.py`

После кода — короткий список: какие функции реально работают, а какие требуют ручного
шага пользователя, и какие проверки ты не смог выполнить.

Никаких пояснений перед кодом. Никаких сокращений внутри кода. Строки патчей — только LF.
