# Установка: Windows и WSL2

## Windows (проверено на этой машине)

Требуется только Python 3.11+ и Git. Внешние зависимости у движка отсутствуют.

```powershell
cd F:\codex-hybrid-engine
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q          # ожидается 89 passed
```

Запуск CLI:

```powershell
.\.venv\Scripts\python.exe -m hybrid.cli --project demo_project doctor
```

Либо поставь точку входа в PATH (после `pip install -e .`):

```powershell
.\.venv\Scripts\hybrid.exe --project demo_project providers
```

### Опциональные инструменты

| Инструмент | Зачем | Как поставить |
|---|---|---|
| Node.js | проверка JS-синтаксиса (`node --check`) при review/apply | уже установлен на этой машине |
| PHP CLI | `php -l` для изменённых `.php` | `winget install PHP.PHP` или OSPanel; без него проверка помечается `SKIP`, а не `PASS` |
| Git | worktree, diff, apply — обязателен | уже установлен |

### Visual QA

Драйвер по умолчанию ищет `chrome.exe` в кэше agent-browser, затем в `PATH`.
Если браузера нет:

```powershell
npm i -g agent-browser
agent-browser install      # скачает Chrome for Testing в %USERPROFILE%\.agent-browser
.\.venv\Scripts\hybrid.exe visual doctor
```

Путь к браузеру можно задать явно в `config/settings.yaml`:

```yaml
visual:
  command: C:\path\to\chrome.exe
  timeout_seconds: 60
```

## WSL2 Ubuntu

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
cd /mnt/f/codex-hybrid-engine
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
pytest -q
hybrid doctor
```

Различия, о которых стоит знать:

- В WSL нет `chrome.exe`-кэша; Visual QA смотри в Windows-часть или укажи
  Linux-браузер через `visual.command`.
- `php -l` работает, если поставить `sudo apt install -y php-cli`.
- Патчи и артефакты пишутся только с LF — на Windows это уже обеспечено кодом,
  отдельная настройка Git не нужна.

## Конфигурация

Два уровня, по возрастанию доверия:

1. `config/settings.yaml` внутри проекта — **недоверенный**. Может включать и
   выключать провайдеров, выбирать модели, но не может перенаправлять API-ключи,
   менять исполняемый файл Codex или расширять список разрешённых файлов.
2. Доверенный пользовательский конфиг — `%XDG_CONFIG_HOME%` (или `~/.config`)
   `codex-hybrid-engine/settings.yaml`, либо путь из `HYBRID_USER_CONFIG`.
   Здесь задаются `providers.codex.command`, `providers.groq.base_url` и
   `context.allowed_files`.

Создать пример проектного конфига:

```powershell
.\.venv\Scripts\hybrid.exe init
```

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `GROQ_API_KEY` | ключ Groq; без него провайдер `UNAVAILABLE` и запросов нет |
| `OPENROUTER_API_KEY` | ключ OpenRouter (провайдер по умолчанию выключен) |
| `HYBRID_DATA_DIR` | каталог состояния вместо `<проект>/.hybrid` |
| `HYBRID_USER_CONFIG` | путь к доверенному конфигу |
| `HYBRID_INSIDE_AGENT=1` | запрещает вложенные агентные вызовы (защита от рекурсии) |

## Проверка после установки

```powershell
.\.venv\Scripts\python.exe -m pytest -q                     # 89 passed
.\.venv\Scripts\hybrid.exe --project demo_project doctor
.\.venv\Scripts\hybrid.exe browser providers                # relay-провайдеры, без сети
.\.venv\Scripts\hybrid.exe visual doctor                    # доступен ли браузер
.\.venv\Scripts\python.exe tools\demo_browser_bridge.py     # демонстрация моста
.\.venv\Scripts\python.exe tools\smoke_visual_qa.py         # реальные скриншоты
```

## Частые проблемы

| Симптом | Причина | Что делать |
|---|---|---|
| `git apply` падает на Windows | патч с CRLF | движок уже пишет патчи с LF; если правил вручную — поставь `core.autocrlf=false` в репозитории проекта |
| `visual doctor` → UNAVAILABLE | браузер не найден | `agent-browser install` или `visual.command` |
| `php -l` не выполняется | нет PHP | это `SKIP`, а не ошибка; поставь `php-cli`, если нужна проверка |
| `hybrid run` отказывается работать | проект не Git-репозиторий | движок не делает `git init`; инициализируй проект сам |
| Codex-провайдер `UNAVAILABLE` | `codex` не в PATH | укажи абсолютный путь в доверенном конфиге: `providers.codex.command` |
