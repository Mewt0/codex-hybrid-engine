# TASK: Visual QA Engine (PHASE 3)

Прикрепи сначала `outbox/00_BOILERPLATE.md`, потом это задание. Больше ничего не нужно.

## Цель

Написать модуль, который проверяет **внешний вид локального веб-приложения** в
настоящем браузере и отдаёт отчёт со скриншотами. Не путать с Browser AI Bridge:
там человек общается с внешним чатом, здесь движок сам открывает локальный сайт.

Драйвер браузера — CLI `agent-browser` (уже установлен в системе). Прямой обёртки
Playwright в проекте нет и добавлять её не надо.

## Что написать

### 1. `hybrid/visual/driver.py`

```python
@dataclass
class Shot:
    viewport: str          # "mobile" | "tablet" | "desktop"
    path: Path             # файл скриншота
    url: str
    ok: bool
    detail: str = ""

@dataclass
class DriverResult:
    ok: bool
    detail: str
    console: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    shots: list[Shot] = field(default_factory=list)

class BrowserDriver(ABC):
    name: str
    def available(self) -> tuple[bool, str]: ...
    def capture(self, url: str, viewports: dict[str, tuple[int, int]], out_dir: Path, session: str) -> DriverResult: ...

class AgentBrowserDriver(BrowserDriver):
    """Drives the `agent-browser` CLI through subprocess."""
    def __init__(self, command: str = "agent-browser", timeout_seconds: int = 120): ...

class FakeDriver(BrowserDriver):
    """Deterministic driver for tests: writes 1x1 PNG files, records calls."""
```

Требования к `AgentBrowserDriver`:

- `command` может быть именем в PATH или абсолютным путём; если не найден —
  `available()` возвращает `(False, "agent-browser not found")`, и это не ошибка.
- на каждый viewport: `open <url>` → `viewport <W> <H>` (или `resize`) → `screenshot <file>`.
  Точные имена подкоманд проверь сам по `agent-browser --help`; если подкоманды нет,
  используй `--viewport WxH` как глобальный флаг и опиши это в `LIMITATIONS`.
- отдельная сессия на запуск: `--session <session>` (передаётся аргументом).
- каждое действие — `subprocess.run(..., capture_output=True, text=True, timeout=...)`;
  `TimeoutExpired` и `FileNotFoundError` превращаются в `DriverResult(ok=False, ...)`, не в падение.
- после `open` собери консольные ошибки и упавшие запросы, если CLI это умеет
  (`agent-browser console` / `agent-browser network requests`). Если не умеет — верни пустые
  списки и явно напиши это в `LIMITATIONS`.
- скриншоты складываются в `out_dir`, имена: `desktop.png`, `tablet.png`, `mobile.png`.
- в конце сессия закрывается (`close`), даже при ошибке (try/finally).

### 2. `hybrid/visual/engine.py`

```python
VIEWPORTS = {"mobile": (390, 844), "tablet": (768, 1024), "desktop": (1440, 900)}

@dataclass
class VisualReport:
    task_id: str
    url: str
    status: str                       # "pass" | "fail" | "not_run"
    checks: list[CheckResult]
    shots: list[Shot]
    report_path: Path | None = None
    def to_dict(self) -> dict: ...

class VisualQA:
    def __init__(self, settings, driver: BrowserDriver | None = None): ...
    def available(self) -> tuple[bool, str]: ...
    def run(self, task_id: str, url: str, viewports: dict[str, tuple[int, int]] | None = None) -> VisualReport: ...
```

Правила:

- каталог артефактов: `<data_dir>/tasks/<TASK-ID>/visual/`; отчёт — `visual/report.json`
  (LF, UTF-8) и краткая markdown-копия `visual/report.md`.
- `status = "not_run"`, если драйвер недоступен; это **не** FAIL, а честная пометка.
  Обязательное правило проекта: неисполненную проверку нельзя выдавать за пройденную.
- `checks` — список `CheckResult` из `hybrid.quality.checks`:
  - `"Browser Driver"` — доступен ли драйвер;
  - `"Screenshots"` — сколько viewport'ов снято (FAIL, если меньше запрошенных);
  - `"Console Errors"` — FAIL, если есть ошибки JS;
  - `"Failed Requests"` — FAIL, если есть 4xx/5xx или оборванные запросы;
  - `"Responsive"` — FAIL, если не снят хотя бы один viewport;
  - `"Visual QA (manual)"` — `"REVIEW"`, потому что оценку «красиво/нет» делает человек.
- в markdown-отчёт вставь ссылки на файлы скриншотов относительными путями.

### 3. `hybrid/visual/__init__.py`

Экспорт: `VIEWPORTS`, `BrowserDriver`, `AgentBrowserDriver`, `FakeDriver`, `DriverResult`,
`Shot`, `VisualQA`, `VisualReport`.

### 4. CLI (правки, а не переписывание)

В `hybrid/cli.py` добавь группу:

```bash
hybrid visual doctor                      # доступен ли драйвер браузера
hybrid visual run TASK-XXXXXXXX --url http://localhost:8000/index.php
hybrid visual run TASK-XXXXXXXX --url ... --viewports desktop,mobile
```

`visual run` вызывает `Controller(settings).status(task_id)`; если задачи нет — понятная
ошибка. Отчёт печатается как JSON и сохраняется в артефакты задачи.

### 5. `tests/test_visual_qa.py`

Минимум 8 тестов на `FakeDriver` (сеть и браузер не запускаются):

1. доступный драйвер → `status == "pass"`, три скриншота в `checks`;
2. недоступный драйвер → `status == "not_run"` и есть `CheckResult("Browser Driver", "FAIL"/"SKIP", ...)`;
3. консольная ошибка → FAIL;
4. упавший запрос → FAIL;
5. снят не все viewport'ы → `"Responsive"` FAIL;
6. `report.json` и `report.md` создаются и валидны;
7. `to_dict()` сериализуется в JSON;
8. `AgentBrowserDriver.available()` не падает, если CLI не найден.

## Чего НЕ делать

- Не устанавливать Playwright, Selenium и прочие зависимости.
- Не запускать реальный браузер из тестов.
- Не ходить в интернет.
- Не менять существующие контракты `CheckResult`, `TaskRecord`, `Controller`.
