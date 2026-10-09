# ЗАДАЧА: Functional QA для `demo_php` (PHP + JS + SQL-контракт)

Прикрепи сначала `00_HEADER.md`, потом это задание.

## Контекст

Есть демо-проект `demo_php/`:

```text
demo_php/
  index.php              # страница инвентаря
  ajax/inventory.php     # JSON-эндпоинт: action=list|item, фильтры rarity/q
  assets/inventory.css
  assets/inventory.js
```

PHP на машине есть: `E:\OSPanel\modules\php\PHP_8.1\php.exe` (+ PHP 5.2…8.1).
В движке уже есть `hybrid.quality.checks.php_binary()`, который его находит.

**Проблема:** Functional QA нет. Синтаксическая проверка (`php -l`) выдаётся за
единственную PHP-проверку, а поведение эндпоинта не проверяется вообще.

## Что нужно

Модуль функциональных проверок, который реально запускает PHP-эндпоинт и
проверяет контракт ответа — **без реальной базы данных**.

### 1. `hybrid/quality/functional.py`

```python
@dataclass
class Scenario:
    name: str
    path: str                    # относительный путь PHP-файла, например "ajax/inventory.php"
    query: dict[str, str]        # GET-параметры
    expect_status: int = 200
    expect_json: bool = True
    required_keys: tuple[str, ...] = ()
    expect_error: bool = False   # payload["ok"] is False ожидается
    post: dict[str, str] | None = None

class FunctionalRunner:
    def __init__(self, project_dir: Path, php: str | None = None, timeout_seconds: int = 20): ...
    def available(self) -> tuple[bool, str]: ...
    def run(self, scenarios: list[Scenario]) -> list[CheckResult]: ...
```

Механика запуска: `php -S 127.0.0.1:0 -t <project_dir>` **или** прямой вызов
`php <file>` с подставленными `$_GET`/`$_POST` через `-r`/`auto_prepend_file`.
Выбери один способ, объясни его в `LIMITATIONS`, и не открывай порт наружу
(Bind только `127.0.0.1`; если поднимаешь сервер — выключай его в `finally`).

Требования:

- если PHP нет → одна проверка `CheckResult("Functional QA", "SKIP", "...")`,
  никакого падения;
- проверки: HTTP-статус, `Content-Type` содержит `application/json` при `expect_json`,
  наличие обязательных ключей, `ok == false` при `expect_error`, отсутствие PHP-ошибок
  (`Parse error`, `Fatal error`, `Warning`, `Notice`) в выводе;
- таймаут на сценарий → `FAIL` с текстом, а не зависание;
- никакого вывода PHP не логировать целиком, только первые 500 символов в `detail`;
- **разрушительные операции SQL не запускать вообще**.

### 2. Интеграция в Quality Engine

В `hybrid/quality/checks.py` добавь функцию:

```python
def run_functional(project_dir: Path, changed: list[str]) -> list[CheckResult]:
    """Run the demo contract scenarios when the change touches PHP/JS."""
```

Правила: сценарии выполняются только если среди `changed` есть `.php`;
иначе `CheckResult("Functional QA", "NOT APPLICABLE", "no PHP files changed")`.
Вызывается из существующего `run_quality()` **после** синтаксических проверок.

### 3. Сценарии для `demo_php`

Отдельный файл `hybrid/quality/scenarios.py` со списком:

```python
DEMO_SCENARIOS = [
    Scenario("list all", "ajax/inventory.php", {"action": "list"}, required_keys=("ok", "items")),
    Scenario("filter by rarity", "ajax/inventory.php", {"action": "list", "rarity": "rare"}, required_keys=("ok", "items")),
    Scenario("search by name", "ajax/inventory.php", {"action": "list", "q": "щит"}, required_keys=("ok", "items")),
    Scenario("single item", "ajax/inventory.php", {"action": "item", "id": "1"}, required_keys=("ok", "item")),
    Scenario("unknown item", "ajax/inventory.php", {"action": "item", "id": "9999"}, expect_status=404, expect_error=True),
    Scenario("unknown action", "ajax/inventory.php", {"action": "nope"}, expect_status=400, expect_error=True),
]
```

### 4. `tests/test_functional_qa.py`

Минимум 8 тестов. Если PHP отсутствует, соответствующие тесты помечай
`pytest.mark.skipif` — но тесты без PHP (SKIP-путь, парсинг ответа, таймаут,
разбор ошибок PHP) должны работать всегда:

1. нет PHP → `FunctionalRunner.available()` = False и `run()` даёт SKIP;
2. PHP есть → сценарий `list all` даёт PASS (skipif);
3. неизвестный item → PASS для сценария с `expect_error` (skipif);
4. неверный `expect_status` → FAIL с понятным detail (можно на фейковом ответе);
5. таймаут → FAIL, тест не висит;
6. PHP-ошибка в выводе (`Parse error`) → FAIL;
7. `run_functional` без PHP-файлов в списке → `NOT APPLICABLE`;
8. `run_quality` на изменённом `.php` включает блок `Functional QA` в результате.

## Не делать

- Не добавлять зависимости, не ставить Composer/PHPUnit, не подключать БД.
- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/browser_bridge/**`,
  `hybrid/visual/**`, `hybrid/local_ui/**`, `demo_php/**`, существующие тесты.
- Не запускать сценарии против реального сайта или реальной базы.
