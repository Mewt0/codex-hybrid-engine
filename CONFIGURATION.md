# Configuration

Create a local config:

```bash
hybrid init
```

This writes `config/settings.yaml`. Keep secrets in environment variables, never in Git.

Important defaults:

- `budget.allow_paid_api: false`
- `budget.max_retries: 1`
- `quality.require_approval: true`
- `quality.auto_merge: false`
- `deepseek_harness.enabled: false`

Forbidden paths are configured under `architecture.forbidden_paths`.

Context sent to external model providers is filtered before request construction. The current MVP excludes `.git`, `.hybrid`, environment files, secret/credential/token/password/private-looking paths, configured forbidden paths, symlinks resolving outside the project, and oversized files.

Cloud context is opt-in. Add only non-sensitive files to:

```yaml
context:
  allowed_files:
    - app.js
    - README.md
```

Preview the exact files before a cloud call:

```bash
hybrid context preview
```

Project configuration is treated as untrusted for executable commands and API
token destinations. `config/settings.yaml` may enable/disable providers and set
safe runtime options, but it cannot override `providers.codex.command` or
`providers.groq.base_url`.

Trusted user configuration is loaded from:

```text
$HYBRID_USER_CONFIG
```

or, when that variable is not set:

```text
~/.config/codex-hybrid-engine/settings.yaml
```

Use this trusted file for a custom Codex command:

```yaml
providers:
  codex:
    command: custom-codex
```

Groq uses `GROQ_API_KEY` from the environment. The key is sent only to the
official HTTPS endpoint `https://api.groq.com/openai/v1`; redirects are blocked.
Custom OpenAI-compatible providers should use a separate provider adapter and a
separate environment variable for their API key.

## Adding a Provider

Add a class under `hybrid/providers/` that implements:

- `available() -> tuple[bool, str]`
- `execute(task, context) -> TaskResult`

Then register it in `Controller._provider`. Keep credentials in environment variables and return a clear unavailable status when a key or executable is missing.

Model providers should return text or a unified diff. Agent providers may change files in the selected working directory; changed files are still read from Git, not trusted from the provider report.

