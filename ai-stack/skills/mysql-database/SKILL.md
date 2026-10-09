---
name: mysql-database
description: Data integrity and query safety for the game database.
triggers: [sql, mysql, database, query, index, migration, transaction, бд, база данных, запрос]
---
# MySQL database

Game data is the most expensive thing to get wrong: a duplicated item or a lost
transaction ruins player trust.

## Rules

- Parameterize every value. Never interpolate user input into SQL.
- Multi-row state changes run inside `START TRANSACTION` / `COMMIT` with
  `ROLLBACK` on any error.
- Inventory, currency and crafting operations must be idempotent or guarded by a
  unique constraint so a double-click cannot duplicate an item.
- Add indexes for columns used in `WHERE`, `JOIN` and `ORDER BY` on large tables.
- Avoid `SELECT *` in new code: name the columns you actually use.
- Never run destructive statements (`DROP`, `TRUNCATE`, unqualified `DELETE`,
  `UPDATE` without `WHERE`) against a real database. Use a fixture or a test schema.

## Migrations

- One logical change per migration, forward and rollback described.
- State which existing rows are affected and what happens to them.
- Never edit a migration that other environments already applied.

## Verification

- The query plan is checked (`EXPLAIN`) for anything touching a large table.
- Foreign keys or explicit integrity checks cover the new relationships.
