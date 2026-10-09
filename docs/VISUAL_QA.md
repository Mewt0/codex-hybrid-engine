# Visual QA

Проверка **внешнего вида локального веб-приложения** в настоящем браузере:
скриншоты на трёх контрольных размерах, консольные ошибки, упавшие запросы,
отчёт в артефактах задачи.

Не путать с Browser AI Bridge: там человек общается с внешним чатом, здесь
движок сам открывает локальную страницу и снимает доказательства.

```bash
hybrid visual doctor
hybrid visual run TASK-XXXXXXXX --url http://localhost:8000/index.php
hybrid visual run TASK-XXXXXXXX --url http://localhost:8000/ --viewports desktop,mobile
```

## Контрольные размеры

| Имя | Размер | Назначение |
|---|---|---|
| `mobile` | 390 x 844 | телефон, портрет |
| `tablet` | 768 x 1024 | планшет, портрет |
| `desktop` | 1440 x 900 | основная игровая поверхность |

## Проверки

| CheckResult | Когда FAIL | Когда SKIP |
|---|---|---|
| `Browser Driver` | браузер не смог открыть страницу | драйвер недоступен |
| `Screenshots` | снято меньше запрошенных размеров | драйвер недоступен |
| `Console Errors` | в логе браузера есть ошибки страницы | драйвер недоступен |
| `Failed Requests` | есть ответы 4xx/5xx (agent-browser) | проверка недоступна у драйвера |
| `Responsive` | не снят хотя бы один размер | драйвер недоступен |
| `Visual QA (manual)` | — | всегда `REVIEW`: «красиво/нет» решает человек |

Статус отчёта: `pass` (все проверки прошли), `fail` (есть FAIL) или `not_run`
(драйвер недоступен). **Неисполненная проверка никогда не выдаётся за пройденную.**

## Драйверы

1. `ChromeScreenshotDriver` (`chrome-headless`) — по умолчанию. Запускает
   `chrome --headless=new --screenshot=... --window-size=WxH` напрямую, один
   запуск на размер (~1 секунда). Ищет бинарник в кэше
   `~/.agent-browser/browsers/**/chrome.exe`, затем в `PATH`; путь можно задать
   в конфиге `visual.command`.
2. `AgentBrowserDriver` (`agent-browser`) — запасной вариант. Использует
   `agent-browser open|viewport|screenshot|console|network`. На этом хосте
   сабкоманда `screenshot` не завершается, поэтому драйвер не является
   основным.

Диагностика самого Chrome (`sandbox\policy`, `network_service_instance_impl`
и подобные строки) отделяется от ошибок страницы, чтобы `Console Errors`
означал ошибки JavaScript, а не шум браузера. Количество отфильтрованных строк
видно в отчёте.

## Артефакты

```
.hybrid/tasks/<TASK-ID>/visual/
  desktop.png
  tablet.png
  mobile.png
  report.json
  report.md
  logs/                 # сырые логи запусков браузера
```

Отчёт попадает и в общий TASK RESULT (`hybrid report TASK-ID`) — поля
`Browser QA`, `Responsive QA`, `Screenshots`.

## Ограничения

- Интерактивность (клики, формы) этим модулем не проверяется: только загрузка
  страницы, вьюпорты, консоль и сетевые ошибки. Сценарии кликов — следующий шаг.
- `Failed Requests` доступен только у драйвера `agent-browser`.
- Chrome на Windows пишет часть диагностики в stderr; она фильтруется по
  списку известных шаблонов, а не «на глаз».
