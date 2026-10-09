# ЗАДАЧА: `hybrid browser context <BTASK-ID>`

Прикрепи сначала `00_HEADER.md`, потом это задание.

## Что нужно

Команда показывает человеку **ровно то, что уйдёт во внешний веб-чат**, до отправки.
Сейчас есть `hybrid context show` (что разрешено вообще) и `browser prompt`
(полный текст запроса), но нет сводки по конкретной задаче.

```bash
hybrid browser context BTASK-XXXXXXXX
hybrid browser context BTASK-XXXXXXXX --json
```

Вывод (человекочитаемый):

```text
Browser task: BTASK-XXXXXXXX
Engine task:  TASK-XXXXXXXX
Provider:     deepseek_web (https://chat.deepseek.com)
Profile:      frontend
Status:       WAITING_FOR_USER

Skills (3):
- beautiful-game-ui
- frontend-development
- browser-testing

Context files (2):
- app.js (1.2 KB)
- index.php (0.8 KB)

Prompt: 4.1 KB, 118 lines
Warnings:
- design/MASTER.md not found

Prompt text: .hybrid/browser-tasks/BTASK-XXXXXXXX/prompt.md
```

`--json` печатает ту же информацию словарём (для скриптов).

## Файлы

1. `hybrid/browser_bridge/context_preview.py` — новый модуль:

```python
@dataclass
class ContextSummary:
    browser_task_id: str
    engine_task_id: str
    provider: str
    provider_url: str
    profile: str
    status: str
    skills: list[str]
    files: list[tuple[str, int]]      # (relative path, size in bytes)
    prompt_chars: int
    prompt_lines: int
    prompt_path: str
    warnings: list[str]
    def to_dict(self) -> dict: ...
    def render(self) -> str: ...

class ContextPreview:
    def __init__(self, bridge, settings): ...
    def build(self, browser_task_id: str) -> ContextSummary: ...
```

2. `hybrid/browser_bridge/__init__.py` — добавить экспорт `ContextPreview`,
   `ContextSummary` (аддитивно).

3. `hybrid/cli.py` — добавить только подкоманду `context` в группу `browser`
   (команда уже есть как имя, проверь, что не конфликтует с `hybrid context`).

4. `tests/test_browser_context.py` — минимум 7 тестов.

## Источник данных

- провайдер и URL — `bridge.provider_status()` или `get_provider(task.provider)`;
- файлы — из сохранённого prompt-артефакта **не** парсингом: возьми `ContextPack`
  через `bridge.context_builder.build(record, record.profile)` и используй
  `pack.used_files()` и `pack.skill_names()`; размеры — `(settings.root / rel).stat().st_size`,
  отсутствующий файл → размер 0 и предупреждение;
- предупреждения — `pack.missing` + `pack.truncated` + «prompt exceeds max_context_chars»,
  если применимо;
- `prompt_path` — из `BrowserTask.prompt_path`.

## Тесты

1. после `prepare` сводка содержит провайдера, профиль и навыки профиля;
2. размеры файлов положительные и соответствуют файлам на диске;
3. `--json` сериализуется (`json.dumps(summary.to_dict())`);
4. `render()` содержит id задачи, провайдера, список файлов и путь к prompt;
5. неизвестный BTASK-ID → понятная ошибка (`BrowserBridgeError`);
6. задача без prompt-файла не падает, а сообщает об этом предупреждением;
7. отсутствующий файл контекста даёт предупреждение и размер 0.

## Не делать

- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/quality/**`,
  `hybrid/context/**`, `hybrid/visual/**`, `hybrid/local_ui/**`, существующие тесты.
- Не делать сетевых запросов и не открывать браузер в тестах.
- Не дублировать логику `PromptBuilder` и `ResponseParser`.
