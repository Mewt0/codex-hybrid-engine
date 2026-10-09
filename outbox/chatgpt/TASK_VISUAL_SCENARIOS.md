# ЗАДАЧА: Интерактивные сценарии Visual QA (клики, формы, модалки)

Прикрепи сначала `00_HEADER.md`, потом это задание.

## Контекст

`hybrid/visual/` уже снимает скриншоты desktop/tablet/mobile настоящим headless
Chrome и проверяет консоль и упавшие запросы. Чего нет: **сценариев действий** —
нажать кнопку, отфильтровать список, открыть модалку, отправить форму и убедиться,
что интерфейс отреагировал.

## Что нужно

### 1. `hybrid/visual/scenarios.py`

```python
@dataclass
class Step:
    action: str                  # "goto" | "click" | "fill" | "select" | "wait_for" | "expect_text" | "screenshot"
    selector: str = ""           # CSS-селектор или текст для expect_text
    value: str = ""              # для fill/select
    timeout_seconds: int = 10
    name: str = ""               # человекочитаемое имя шага

@dataclass
class Scenario:
    name: str
    url: str
    steps: list[Step]
    viewport: str = "desktop"

@dataclass
class StepResult:
    step: str
    ok: bool
    detail: str = ""
    screenshot: Path | None = None

@dataclass
class ScenarioResult:
    scenario: str
    ok: bool
    steps: list[StepResult]
    console: list[str]
    failed_requests: list[str]
    def to_dict(self) -> dict: ...
```

### 2. `hybrid/visual/driver.py` — расширение драйвера

Добавь в `BrowserDriver` и `ChromeScreenshotDriver` метод:

```python
def interact(self, scenario: Scenario, out_dir: Path) -> ScenarioResult:
    ...
```

Интерактивность через Chrome CLI **невозможна**, поэтому используй один из двух
честных путей и явно опиши выбранный в `LIMITATIONS`:

- **предпочтительно:** `agent-browser` CLI (`open`, `click`, `fill`, `select`,
  `wait`, `get text`, `screenshot`) — он установлен на машине и умеет это;
- запасной: `ScenarioResult(ok=False, ...)` с деталью «interactive driver unavailable».

Если выбран `agent-browser`, оберни вызовы так же, как уже сделано в
`AgentBrowserDriver._run()`: вывод в файл, жёсткий таймаут, никаких наследованных
пайпов (иначе зависает). Каждый шаг логируется, а скриншот снимается после
последнего шага и при падении шага.

### 3. `hybrid/visual/engine.py` — интеграция

```python
class VisualQA:
    def run_scenarios(self, task_id: str, scenarios: list[Scenario]) -> list[ScenarioResult]: ...
```

- артефакты: `<data_dir>/tasks/<TASK-ID>/visual/scenarios/<scenario-name>/`,
  скриншоты `step-01.png`… и `final.png`;
- `checks` дополняются `CheckResult("Scenario: <name>", "PASS"/"FAIL", detail)`;
- недоступный интерактивный драйвер → `CheckResult("Scenario Runner", "SKIP", ...)`,
  **не** FAIL и **не** PASS;
- существующий `run()` (скриншоты вьюпортов) не менять.

### 4. `hybrid/quality/scenarios.py` — сценарии для `demo_php`

Демо-страница `demo_php/index.php`: поле поиска `#search`, селект `#rarity`,
кнопка `#refresh`, сетка `#grid`, статус `#status`.

```python
DEMO_UI_SCENARIOS = [
    Scenario("inventory loads", "http://127.0.0.1:<port>/index.php", [
        Step("goto"), Step("wait_for", selector="#grid .card"), Step("expect_text", selector="#status", value="Предметов"),
    ]),
    Scenario("filter by rarity", ..., [
        Step("goto"), Step("wait_for", "#grid .card"), Step("select", "#rarity", "rare"),
        Step("wait_for", "#grid .card"), Step("expect_text", "#status", "Предмет"),
    ]),
    Scenario("search by name", ..., [
        Step("goto"), Step("wait_for", "#grid .card"), Step("fill", "#search", "щит"),
        Step("wait_for", "#grid .card"),
    ]),
    Scenario("use item", ..., [
        Step("goto"), Step("wait_for", "#grid button"), Step("click", "#grid button"),
        Step("expect_text", "#status", "Выбран предмет"),
    ]),
]
```

Порт подставляется аргументом: сделай функцию
`build_demo_scenarios(base_url: str) -> list[Scenario]`.

### 5. CLI

```bash
hybrid visual scenarios TASK-XXXXXXXX --url http://127.0.0.1:8000/index.php
```

Печатает JSON со `ScenarioResult`-ами и сохраняет их в артефакты задачи.

### 6. `tests/test_visual_scenarios.py`

Минимум 8 тестов без реального браузера (используй `FakeDriver`/заглушку
интерактивного драйвера):

1. недоступный интерактивный драйвер → `SKIP`, не FAIL и не PASS;
2. сценарий из 3 успешных шагов → `ok=True`, 3 `StepResult`;
3. падение шага `wait_for` → `ok=False`, последующие шаги не выполняются;
4. `screenshot` после шага создаёт файл;
5. `ScenarioResult.to_dict()` сериализуется;
6. `build_demo_scenarios()` подставляет базовый URL во все сценарии;
7. `run_scenarios` добавляет `CheckResult` на каждый сценарий;
8. в артефактах появляется каталог сценария с логами.

## Не делать

- Не добавлять Playwright и другие зависимости.
- Не запускать реальный браузер из тестов.
- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/browser_bridge/**`,
  `hybrid/local_ui/**`, `hybrid/context/**`, `demo_php/**`, существующие тесты.
- Не выдавать пропущенный сценарий за пройденный.
