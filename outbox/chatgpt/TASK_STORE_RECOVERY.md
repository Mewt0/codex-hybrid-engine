# ЗАДАЧА: Устойчивость Browser Task Store к аварийному завершению

Прикрепи сначала `00_HEADER.md`, потом это задание.

## Проблема

`hybrid/browser_bridge/sessions.py` пишет `metadata.json` и `index.json`
**отдельными** атомарными записями. Если процесс упал между ними, `index.json`
отстаёт: задача есть в файле задачи, но её нет в индексе. Сейчас это никак не
проверено и не восстановимо.

## Что нужно

### 1. `hybrid/browser_bridge/sessions.py` — починка (аккуратно, файл небольшой)

Добавь:

```python
def all(self) -> dict[str, dict]:
    """Read the index; repair missing entries from task metadata files."""

def repair_index(self) -> dict[str, dict]:
    """Rebuild index entries from *.metadata.json on disk. Never deletes a task."""

def verify(self) -> list[str]:
    """Return a list of consistency problems (index vs metadata files)."""
```

Требования:

- `all()` при расхождении **не теряет** задачу: подтягивает запись из
  `browser-tasks/<TASK>/metadata.json`, если файл валиден; повреждённый файл —
  пропускает и запоминает в `verify()`;
- `repair_index()` перезаписывает `index.json` из файлов задач атомарно и
  возвращает результат; никогда не удаляет задачу;
- `verify()` сообщает: `"missing-in-index: BTASK-X"`, `"missing-metadata: BTASK-Y"`,
  `"corrupt-metadata: BTASK-Z"`;
- публичное поведение `save()`, `get()`, `history()`, `import_response()`,
  `write_review()` не меняется;
- `get()` для задачи, которой нет в индексе, но есть метаданные, **должен** её вернуть.

### 2. CLI

```bash
hybrid browser verify          # печатает проблемы; код возврата 0 если чисто, 1 если нет
hybrid browser repair          # восстанавливает индекс из файлов задач
```

Добавляй подкоманды в `hybrid/cli.py` в группу `browser`, больше там ничего не трогай.

### 3. `tests/test_browser_store_recovery.py`

Минимум 8 тестов, все — на временном каталоге:

1. задача есть в metadata, нет в index → `all()` её возвращает;
2. `get()` возвращает такую задачу;
3. `verify()` сообщает `missing-in-index`;
4. `repair_index()` восстанавливает запись, после чего `verify()` пуст;
5. повреждённый `metadata.json` → `verify()` сообщает `corrupt-metadata`, исключения нет;
6. `history()` не падает при расхождении;
7. `repair_index()` не удаляет существующие задачи (сравнить количество до/после);
8. `import_response()` продолжает работать после `repair_index()`.

## Не делать

- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/state.py`,
  `hybrid/quality/**`, `hybrid/context/**`, `hybrid/visual/**`,
  `hybrid/local_ui/**`, существующие тесты.
- Не удалять задачи при «ремонте».
- Не менять формат `metadata.json` и имена файлов.
