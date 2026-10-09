# ЗАДАЧА: Проверка дизайн-системы (CSS-токены против Design Memory)

Прикрепи сначала `00_HEADER.md`, потом это задание.

## Контекст

Design Memory лежит в `ai-stack/design/*.md` (`COLORS.md`, `TYPOGRAPHY.md` и т.д.)
и попадает в промпт моделям. Но **ничто не проверяет**, что реальный CSS проекта
следует этой памяти: модель может придумать свои цвета, и это никто не заметит.

## Что нужно

### 1. `hybrid/quality/design_tokens.py`

```python
@dataclass
class Token:
    name: str          # "--color-accent"
    value: str         # "#d8a13a"
    source: str        # "css" | "design-memory"

@dataclass
class DesignCheck:
    name: str
    status: str        # PASS | WARN | FAIL | SKIP
    detail: str = ""

class DesignTokenChecker:
    def __init__(self, settings, project_dir: Path | None = None): ...
    def memory_tokens(self) -> dict[str, str]:
        """Parse `--token | value` rows out of the design markdown tables."""
    def css_tokens(self, files: list[str]) -> dict[str, str]:
        """Collect custom properties from the given CSS files."""
    def check(self, changed: list[str]) -> list[CheckResult]: ...
```

Правила:

- Токены из markdown берутся из таблиц вида `| `--color-bg` | `#0e1116` | … |`
  (имя в бэктиках, значение в бэктиках) — только из `ai-stack/design/COLORS.md`
  и `TYPOGRAPHY.md`;
- CSS-токены — только из файлов, перечисленных в `changed` (и только `.css`);
- проверки:
  - `Design: tokens present` — в изменённом CSS есть `:root` с переменными (`WARN`, если нет);
  - `Design: unknown tokens` — переменные, которых нет в Design Memory (`WARN`, перечислить);
  - `Design: token value drift` — одноимённая переменная с другим значением (`FAIL`, показать оба значения);
  - `Design: hardcoded colors` — hex-цвета вне `:root` (`WARN`, посчитать);
  - `Design: skipped` — `SKIP`, если нет ни design-файлов, ни изменённых CSS.
- **Никакой автоматической правки файлов.** Только отчёт.

### 2. Интеграция

В `hybrid/quality/checks.py` добавь:

```python
def run_design_checks(project_dir: Path, changed: list[str], settings) -> list[CheckResult]:
```

и вызывай из `run_quality` **только если** среди `changed` есть `.css`
(иначе `CheckResult("Design", "NOT APPLICABLE", "no CSS changed")`).
Учти: `run_quality(project_dir, changed)` сейчас вызывается из `controller.py`
без `settings`. Не ломай сигнатуру: сделай `settings=None` по умолчанию и при
`None` возвращай `CheckResult("Design", "SKIP", "settings not provided")`.

### 3. `tests/test_design_tokens.py`

Минимум 9 тестов (реальный CSS и markdown во временных файлах):

1. парсинг токенов из markdown-таблицы;
2. парсинг `:root` переменных из CSS;
3. совпадающие токены → PASS;
4. незнакомый токен в CSS → WARN с именем;
5. расхождение значения → FAIL с обоими значениями;
6. hex-цвета вне `:root` → WARN с количеством;
7. нет изменённых CSS → NOT APPLICABLE;
8. `settings=None` → SKIP, без исключения;
9. проверка не меняет файлы на диске (сравнить хэши до/после).

## Не делать

- Не добавлять зависимости (парсинг — регулярными выражениями).
- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/browser_bridge/**`,
  `hybrid/visual/**`, `hybrid/local_ui/**`, `hybrid/context/**`, существующие тесты.
- Не превращать WARN в FAIL: предупреждение — это предупреждение.
