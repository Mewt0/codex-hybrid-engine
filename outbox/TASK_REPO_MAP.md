# TASK: Repo Map (PHASE 4)

Прикрепи сначала `outbox/00_BOILERPLATE.md`, потом это задание.

## Цель

Дать модели компактное понимание структуры legacy PHP/JS-проекта, чтобы контекст
собирался из **связанных** файлов, а не из «первые восемь по алфавиту».

Точный граф зависимостей в legacy PHP построить нельзя (динамические `include`,
глобальные переменные, вызовы через AJAX). Поэтому нужна эвристика и три честных
состояния зависимости: `independent`, `dependent`, `unknown`.

## Что написать

### 1. `hybrid/context/repo_map.py`

```python
@dataclass
class SymbolRef:
    name: str
    kind: str            # "function" | "class" | "const" | "endpoint" | "include"
    path: str
    line: int

@dataclass
class FileNode:
    path: str
    language: str                      # "php" | "js" | "css" | "html" | "sql" | "other"
    symbols: list[SymbolRef] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)      # пути, которые файл подключает/требует
    endpoints: list[str] = field(default_factory=list)     # URL/имена AJAX-обработчиков
    referenced_by: list[str] = field(default_factory=list)

@dataclass
class RepoMap:
    nodes: dict[str, FileNode]
    relations: dict[str, str]          # "a.php -> b.php": "independent" | "dependent" | "unknown"
    generated_at: float
    truncated: bool = False
    def summary(self, limit: int = 40) -> str: ...
    def related(self, path: str, depth: int = 2) -> list[str]: ...
    def to_dict(self) -> dict: ...

class RepoMapBuilder:
    def __init__(self, settings, max_files: int = 400, max_bytes: int = 2_000_000): ...
    def build(self) -> RepoMap: ...
    def cache_path(self) -> Path: ...
    def load_cached(self) -> RepoMap | None: ...
    def save(self, repo_map: RepoMap) -> Path: ...
```

Требования к анализу — только регулярные выражения и стандартная библиотека:

- PHP: `function name(`, `class Name`, `include`/`include_once`/`require`/`require_once`
  с литеральным путём (в одинарных/двойных кавычках) — без выполнения кода;
- JS: `function name(`, `const name = (`/`function`, `fetch("...")`/`$.post("...")`
  как endpoint-ссылки;
- CSS: `@import "..."`, имена классов верхнего уровня (только счётчик, без списка);
- endpoint'ы сопоставляй с PHP-файлами по имени вхождения (эвристика: если файл
  `ajax/inventory.php` и в JS есть `inventory.php` — это `dependent`);
- `relations` заполняй так: `dependent` при явном include/AJAX-совпадении, `independent`
  при доказанном отсутствии общих символов и endpoints, иначе `unknown`;
- `unknown` никогда не считается независимым: в `related()` он идёт в выдачу.

Ограничения по объёму: не читать файлы больше 256 КБ, не индексировать
`node_modules`, `vendor`, `.git`, `.hybrid`, `dist`, `build`, `.venv`;
файлы длиннее 20 000 строк читать только до 20 000 строк.

### 2. Кэш

`<data_dir>/repo-map.json` — LF, UTF-8, сортированные ключи. Кэш валиден, если
`generated_at` новее максимального `mtime` проиндексированных файлов.

### 3. Интеграция с Context Pack

В `hybrid/context/__init__.py` добавь **не ломая существующий API**:

- `ContextBuilder.__init__(..., repo_map: RepoMap | None = None)`;
- если `repo_map` передан, `_relevant_files()` сначала берёт `repo_map.related(...)`
  от файлов, наиболее близких к профилю (для `frontend` — `.js`/`.css`, для
  `backend-php` — `.php`), и только потом добирает остальное из `allowed_files`;
- в `ContextPack` добавь поле `repo_map_summary: str = ""` и включай его в
  `render_prompt()` отдельной секцией `# REPO MAP`, но **только** если он непустой;
- список `allowed_files` остаётся единственным источником того, что вообще можно читать.

### 4. CLI

```bash
hybrid map build [--force]        # построить и закэшировать
hybrid map show [--limit 40]      # краткая сводка
hybrid map related PATH [--depth 2]
```

### 5. `tests/test_repo_map.py`

Минимум 9 тестов на временной файловой структуре (PHP+JS+CSS+SQL):

1. включения PHP (`include "a.php"`) дают `dependent`;
2. AJAX-вызов в JS и одноимённый PHP-файл дают `dependent`;
3. файлы без связей и совпадений дают `independent` только при доказанном отсутствии символов;
4. `related()` возвращает транзитивные связи, `unknown` не отбрасывается;
5. тяжёлые каталоги (`vendor/`, `node_modules/`) не индексируются;
6. файл больше лимита читается усечённо и не валит сборку;
7. кэш переиспользуется и обновляется при изменении файла;
8. `ContextPack.repo_map_summary` пустой, если `repo_map` не передан (обратная совместимость);
9. существующие 69 тестов проекта не должны сломаться (прогони `pytest -q`).

## Чего НЕ делать

- Не вызывать LLM для построения карты.
- Не добавлять tree-sitter, LSP, networkx и прочие зависимости.
- Не исполнять код проекта и не делать сетевых запросов.
- Не менять местами `allowed_files` и карту: карта только ранжирует уже разрешённое.
