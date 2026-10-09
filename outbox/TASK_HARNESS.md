# TASK: DeepSeek Harness Adapter (PHASE 5, необязательный модуль)

Прикрепи сначала `outbox/00_BOILERPLATE.md`, потом это задание.

## Цель

Сделать **необязательный** адаптер к официальному Python SDK DeepSeek Harness.
Harness не должен становиться обязательной зависимостью: без него всё работает
как сейчас. Никаких платных вызовов моделей без явного разрешения.

## Важное правило честности

Ты не можешь подтвердить, что SDK установлен и что интерфейс именно такой, какой
ты предполагаешь. Поэтому:

- весь код, зависящий от SDK, изолирован и импортируется **лениво**, внутри методов;
- если SDK нет — `available()` возвращает `(False, "deepseek-harness-sdk is not installed")`,
  а вызов задачи даёт понятную ошибку, а не `ImportError` из недр;
- **не выдумывай имена методов и модулей SDK**. Если ты не уверен в точном имени,
  вынеси обращение в одно место (`_load_sdk()`) и напиши это в `LIMITATIONS` прямым
  текстом: «имя интерфейса не проверено, требует сверки с документацией».

## Что написать

### 1. `hybrid/integrations/deepseek_harness.py` (заменить существующую заглушку)

Существующий файл сейчас:

```python
class DeepSeekHarnessAdapter:
    """Optional boundary; no undocumented CLI/API is assumed."""
    name = "deepseek_harness"
    def available(self) -> tuple[bool, str]: ...
```

Сохрани имя класса `DeepSeekHarnessAdapter` и `name = "deepseek_harness"` — их
использует `hybrid/cli.py`. Добавь:

```python
@dataclass
class HarnessResult:
    status: str            # "ok" | "unavailable" | "error"
    output: str = ""
    error: str | None = None
    duration_seconds: float = 0.0

class DeepSeekHarnessAdapter:
    def __init__(self, config: dict): ...        # config = settings.raw["deepseek_harness"]
    def available(self) -> tuple[bool, str]: ...
    def run_task(self, description: str, cwd: Path, timeout: int | None = None) -> HarnessResult: ...
```

Правила `run_task`:

- `enabled: false` в конфиге → `HarnessResult("unavailable", error="disabled by configuration")`,
  сеть и SDK не трогаются;
- ограничение параллельных агентов (`max_parallel_agents`) и таймаут (`timeout_seconds`)
  берутся из конфига; таймаут — жёсткий, превышение даёт `HarnessResult("error", ...)`;
- рекурсия запрещена: если в окружении видно, что мы уже внутри агентного процесса
  (например, переменная `HYBRID_INSIDE_AGENT=1`), задача не запускается;
- результаты не логируют содержимое секретов; API-ключи провайдеров в дочернее
  окружение не передаются (используй белый список переменных, как в `CodexProvider._safe_env`).

### 2. Feature flag в конфиге

В `hybrid/config.py` уже есть блок:

```python
"deepseek_harness": {"enabled": False, "max_parallel_agents": 2, "timeout_seconds": 180}
```

Добавь валидацию: `enabled` — bool, `max_parallel_agents` — положительный int,
`timeout_seconds` — положительный int. Неверные типы → `ValueError` с понятным текстом.
Значения по умолчанию менять нельзя: по умолчанию выключено.

### 3. CLI

```bash
hybrid harness doctor     # доступен ли SDK, включён ли флаг, какая версия (если видна)
```

Никакой команды «запусти задачу в Harness» в первой версии не добавляй: сначала
нужно подтвердить интерфейс вручную.

### 4. `tests/test_harness_adapter.py`

Минимум 7 тестов, сеть и SDK не используются:

1. `enabled: false` → `available()` = False, `run_task` не падает;
2. SDK отсутствует (подставь фейковый `importlib` или несуществующий модуль) → понятная ошибка;
3. поддельный SDK-модуль через `monkeypatch.setitem(sys.modules, ...)` → `run()` возвращает `ok`;
4. таймаут поддельного SDK → `HarnessResult("error")` без зависания теста;
5. `HYBRID_INSIDE_AGENT=1` → задача не запускается, внятная причина;
6. ключи `GROQ_API_KEY`/`OPENROUTER_API_KEY` не попадают в окружение дочернего вызова;
7. неверный тип `max_parallel_agents` в конфиге → `ValueError`.

## Чего НЕ делать

- Не добавлять `deepseek-harness-sdk` в `pyproject.toml` как обязательную зависимость.
- Не вызывать реальные модели и не тратить деньги.
- Не ломать существующий вывод `hybrid providers` (там печатается статус адаптера).
- Не утверждать в отчёте, что живая интеграция проверена, если ты её не запускал.
