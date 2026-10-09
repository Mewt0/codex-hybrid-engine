# TASK: Локальный Web Workspace (`hybrid ui`)

Прикрепи сначала `outbox/00_BOILERPLATE.md`, потом это задание.

## Цель

Лёгкий локальный веб-интерфейс, из которого проходится весь цикл Browser Relay
без запоминания CLI-команд: подготовить запрос → скопировать → открыть веб-чат →
вставить ответ → посмотреть проверки и diff → применить.

**Только стандартная библиотека Python** (`http.server`, `json`, `html`).
Не добавлять Flask, FastAPI, React, Electron, шаблонизаторы, CSS-фреймворки.

## Что написать

### Структура

```text
hybrid/local_ui/
  __init__.py
  server.py        # сборка HTTPServer, запуск, остановка
  handlers.py      # обработчики запросов и роутинг
  renderer.py      # HTML-страницы (f-strings, без шаблонизатора)
  security.py      # проверки Origin/CSRF/путей
tests/test_local_ui.py
```

### Интерфейс сервера

```python
class LocalUI:
    def __init__(self, settings, bridge, controller, host: str = "127.0.0.1", port: int = 8765): ...
    def url(self) -> str: ...                     # http://127.0.0.1:<port>/
    def start(self, block: bool = True) -> str: ...   # печатает URL, block=False для тестов
    def stop(self) -> None: ...
    @property
    def server(self) -> "HTTPServer": ...
```

Требования:

- слушать **только** `127.0.0.1`; если передан другой host — `ValueError`;
- порт `0` разрешён (тесты берут свободный порт), фактический порт читается из `server.server_address`;
- `start(block=False)` возвращает URL и не блокирует; `stop()` корректно завершает `serve_forever`;
- никаких потоков-демонов, трекеров, фоновых задач, чтения буфера обмена.

### Маршруты

| Метод | Путь | Действие |
|---|---|---|
| GET | `/` | Dashboard: список задач (`bridge.history()`) со статусами и ссылками |
| GET | `/new` | форма: описание, провайдер (select), профиль (select) |
| POST | `/prepare` | `bridge.prepare(description, provider, profile)` → редирект на `/task/<BTASK>` |
| GET | `/task/<BTASK>` | карточка: статус, провайдер, профиль, навыки, файлы контекста, предупреждения, запрос, поле ответа, кнопки |
| POST | `/import` | `bridge.import_response(BTASK, text, force)` → редирект на `/task/<BTASK>` |
| GET | `/diff/<BTASK>` | `text/plain` полный diff |
| GET | `/review/<BTASK>` | JSON `bridge.review_payload(BTASK)` |
| POST | `/apply` | `controller.apply(engine_task_id, confirm=True)` — **только при непустом поле `confirm`, равном `APPLY`** |
| GET | `/open/<BTASK>` | вызывает `bridge.open(BTASK)`, показывает URL и инструкцию |
| GET | `/api/tasks` | JSON история |
| GET | `/health` | `{"status": "ok", "tasks": <n>}` |

Ошибки: неизвестный путь → 404, неизвестная задача → 404, исключение
`BrowserBridgeError`/`ResponseAlreadyImported` → 409 с текстом ошибки,
неверный CSRF/Origin → 403. Никаких голых трейсбеков в ответе.

### Безопасность (обязательно)

- `security.py`:
  - `same_origin_ok(headers, host, port) -> bool` — проверка заголовка `Origin`
    (если он есть, он должен совпадать с адресом сервера) и `Host`;
  - `csrf_token() -> str` и `check_csrf(form, expected) -> bool` — токен
    генерируется на запуск сервера, встроен в формы и проверяется на POST;
  - все POST без валидного токена → 403.
- Никаких произвольных команд, путей, eval, exec.
- Никакой отдачи файлов вне артефактов задач; `/diff` и `/prompt` отдают только
  содержимое артефактов конкретной задачи.
- HTML экранируется: `html.escape()` для всех подставляемых значений.
- Тело POST ограничено 1 МБ (иначе 413).

### CLI

```bash
hybrid ui [--host 127.0.0.1] [--port 8765] [--no-browser]
```

Печатает URL. Если не `--no-browser`, открывает URL тем же способом, что
провайдеры (`webbrowser.open`), и **не падает**, если открыть не удалось.
Работает через существующий `BrowserBridge` и `Controller`; второго пути
применения изменений не создавать.

### Тесты `tests/test_local_ui.py`

Минимум 12 тестов, без сети наружу, сервер поднимается на порту 0:

1. `LocalUI(host="0.0.0.0")` → `ValueError`;
2. `start(block=False)` возвращает URL, `/health` отвечает `ok`;
3. `/` содержит id задачи после `prepare`;
4. POST `/prepare` создаёт задачу и редиректит;
5. POST без CSRF → 403;
6. POST с чужим `Origin` → 403;
7. GET неизвестной задачи → 404;
8. импорт валидного патча → статус `ready_for_review`, `/diff` отдаёт патч;
9. повторный импорт → 409;
10. `/apply` без `confirm=APPLY` → 409/403 и проект не изменён;
11. `/apply` с `confirm=APPLY` → проект изменён (проверить файл);
12. HTML экранирование: описание задачи с `<script>` не попадает сырым в HTML;
13. тело POST больше лимита → 413.

## Чего НЕ делать

- Не добавлять зависимости и не менять `pyproject.toml` (кроме, при необходимости, ничего).
- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/state.py`,
  `hybrid/quality/**`, `hybrid/context/**`, `hybrid/browser_bridge/**`,
  `hybrid/visual/**` и существующие тесты.
- Не трогать `outbox/**`.
- Не открывать сервер в интернет, не логировать содержимое ответов модели.
- Не запускать браузер из тестов.
- Все текстовые файлы — LF.
