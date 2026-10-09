# QA Round 3

QA3 fixes three security regressions reported after `codex-hybrid-engine-qa2.zip`.

## Fixed

- Model-provider patch paths are now derived with Git machine-readable output:
  `git apply --numstat -z`. The controller no longer trusts textual `+++ b/`
  header parsing.
- Patch validation replays the exact artifact in a disposable repository,
  forces intent-to-add for affected paths, and rejects a non-empty patch when
  no changed files can be determined.
- Ignored files created by a patch, such as `.env`, are included in validation
  and blocked by architecture rules.
- Project YAML cannot override `providers.codex.command` or
  `providers.groq.base_url`. Those fields are accepted only from trusted user
  configuration.
- Groq sends `GROQ_API_KEY` only to `https://api.groq.com/openai/v1`, requires
  HTTPS, blocks redirects, and does not log secrets.

## New CLI helpers

```bash
hybrid context preview
hybrid providers
```

`context preview` shows the exact files selected for cloud context. The default
cloud context is empty until `context.allowed_files` explicitly names safe files.

`providers` now displays provider options and whether trusted-only fields came
from the default configuration or trusted user configuration. Secret-looking
values are masked.

## Trusted configuration model

Project configuration lives at `config/settings.yaml` and is useful for ordinary
project policy:

- provider enabled flags
- timeouts
- model IDs
- architecture and context rules
- budget limits

Trusted user configuration is loaded from `$HYBRID_USER_CONFIG` or
`~/.config/codex-hybrid-engine/settings.yaml`. It is the only place where a user
may approve non-default executable commands and token destinations.

Project-controlled values for these fields are ignored:

- `providers.codex.command`
- `providers.groq.base_url`

Custom OpenAI-compatible providers should be implemented as separate provider
adapters with their own API-key environment variables.

## Test result

```text
40 passed in 3.45s
```

The suite includes all 33 QA2 tests plus reconstructed QA3 regressions for:

- Git-derived patch path validation with ignored protected files.
- Project config command override rejection.
- Trusted user command override support.
- Groq API key URL protection.
- Project config Groq redirect rejection.

## Remaining limitations

- Git worktrees, temporary copies, and validation checks are program-level
  controls. They are not a full operating-system sandbox for malicious code.
- The engine still does not run live Codex or Groq calls during automated tests.
  Codex and Groq are tested through availability checks, configuration checks,
  mock providers, and provider error handling.
- DeepSeek Harness remains disabled and unverified in this MVP.
