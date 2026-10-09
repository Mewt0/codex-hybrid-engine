---
name: security-review
description: Security pass over changes touching auth, sessions, input or files.
triggers: [security, auth, authoriz, password, session, sql injection, xss, csrf, upload, безопасн, парол, авторизац, уязвим]
---
# Security review

Run this pass on any change that touches authentication, authorization,
sessions, user input, file handling or SQL.

## Checklist

- **SQL injection** — every query parameterized; no concatenated user input.
- **XSS** — output escaped for HTML context; JSON responses use
  `Content-Type: application/json`, never HTML with embedded data.
- **CSRF** — state-changing endpoints require a token or a same-site,
  non-GET-only contract.
- **Authorization** — the endpoint checks the session *and* that the acting
  player owns the resource; never trust an id from the request body.
- **Session** — session id regenerated on privilege change; logout invalidates
  server-side state.
- **File upload** — extension and MIME allowlist, stored outside the web root or
  with execution disabled, filename generated server-side.
- **Secrets** — no keys or credentials in the repository, in logs or in the
  client payload.
- **Errors** — no stack traces or SQL errors returned to the client.
- **Rate** — expensive or state-changing actions have a server-side limit.

## Output

Report each finding with file, line, concrete impact and the minimal fix.
If a category is clean, say so instead of staying silent.
