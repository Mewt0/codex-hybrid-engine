# ЗАДАЧА: PHP SQL-профиль — тексты навыков `php-sql-contracts`

Прикрепи сначала `00_HEADER.md`, потом это задание.

## Контекст

Есть профиль `database` (навыки `mysql-database`, `security-review`) и
`backend-php` (`php-legacy`, `mysql-database`, `security-review`). Не хватает
навыка, который связывает PHP-эндпоинт и SQL-контракт: как проверить, что
AJAX-обработчик не сломает целостность игровых данных.

## Что нужно

**Только markdown-файлы**, никакого Python-кода.

### 1. `ai-stack/skills/php-sql-contracts/SKILL.md`

Frontmatter строго в этом формате (его читает `SkillLibrary`):

```markdown
---
name: php-sql-contracts
description: <одно предложение>
triggers: [php, sql, ajax, transaction, inventory, эндпоинт, транзакц, инвентар]
---
```

Содержание — практические правила, без воды:

- контракт эндпоинта: вход (параметры, типы, обязательность), выход (ключи JSON,
  коды), идемпотентность;
- проверка прав до записи, а не после;
- одна транзакция на одно действие игрока (`START TRANSACTION` / `COMMIT` / `ROLLBACK`);
- защита от двойного клика: уникальный ключ или серверная проверка состояния;
- денежные и предметные операции: `SELECT … FOR UPDATE` там, где это нужно;
- где именно валидировать вход (на границе), а где — бизнес-правила;
- как оформлять SQL-ошибки в ответе (без утечки текста драйвера);
- что **нельзя** делать в демо/тестовой среде: `DROP`, `TRUNCATE`, `DELETE`/`UPDATE` без `WHERE`.

Объём — до 60 строк. Короткие примеры на PHP + SQL допустимы.

### 2. Подключение к профилям

Обнови `ai-stack/profiles/backend-php.yaml` и `ai-stack/profiles/database.yaml`:
добавь `php-sql-contracts` в `skills:` (остальные навыки не убирай).

Обнови `hybrid/context/__init__.py`: в словаре `PROFILES` добавь навык в
`backend-php`, `database` и `fullstack-game`. **Ничего больше в этом файле не меняй.**

### 3. `tests/test_php_sql_skill.py`

Минимум 4 теста:

1. `SkillLibrary` загружает `php-sql-contracts` и видит `triggers`;
2. профиль `database` содержит новый навык;
3. профиль `backend-php` содержит новый навык;
4. `ContextBuilder.build(task, "database")` включает текст навыка в промпт.

## Не делать

- Не добавлять внешние skill-пакеты и зависимости.
- Не менять другие навыки и дизайн-файлы.
- Не менять `hybrid/controller.py`, `hybrid/tasks.py`, `hybrid/quality/**`,
  `hybrid/browser_bridge/**`, `hybrid/visual/**`, `hybrid/local_ui/**`,
  существующие тесты.
