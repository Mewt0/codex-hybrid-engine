---
name: php-legacy
description: Safe changes to legacy PHP game backends without a rewrite.
triggers: [php, endpoint, api, ajax, session, авторизац, сессия, бэкенд, backend, controller]
---
# Legacy PHP

The project is legacy PHP. Compatibility beats elegance: do not modernize
unrelated code, do not rename public functions, do not reformat whole files.

## Rules

- Detect the PHP version assumptions of the file you touch and stay within them.
- Every new endpoint: validate input, check the session/permission, then act.
- Use prepared statements (`PDO`/`mysqli` with bound parameters) for any query
  that contains user input. String concatenation into SQL is a defect.
- Escape output with `htmlspecialchars($value, ENT_QUOTES, 'UTF-8')`.
- Never echo raw exception messages or SQL errors to the client; log them.
- Keep the response shape stable: existing JavaScript depends on existing keys.
- Wrap multi-step state changes (inventory moves, currency) in a transaction.
- Guard against repeated submissions (idempotency key or server-side state check).

## Do not

- Add Composer dependencies, a framework or an autoloader to a legacy entry point.
- Rewrite `include`-based includes into PSR-4 classes.
- Switch to typed properties or enums in files that must run on old PHP.

## Verification

- `php -l` passes on every changed file.
- The endpoint returns the documented shape on success and on failure.
- No new SQL built by string concatenation.
