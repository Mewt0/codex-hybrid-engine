# Testing

Run:

```bash
python -m pytest
```

Covered scenarios:

- Fast mode returns changes and does not modify the main project before approval.
- Safe mode creates a separate worktree.
- Forbidden files are rejected.
- Invalid patches are not applied.
- Missing Groq API key has a clear message.
- Dry run stores task history.
- JavaScript syntax errors are detected.
- Parent traversal and symlink escape are rejected.
- CLI remains usable without cloud credentials.
- Groq 429 is surfaced with a bounded retry policy.
- Apply requires explicit confirmation.
- Confirmed apply works once and repeat apply is rejected.
- Provider errors cannot become ready-for-review tasks.
- New files created by an agent are included in Git change detection.
- Plain non-Git directories are rejected without auto init/commit.
- Protected and secret-looking files are excluded from external-provider context.
- Project changes between review and apply are detected.
- Patches are stored per task and do not share a global `last.patch`.
- Model-provider patches are validated in a temporary copy before review.
- FAST agent temporary copies exclude protected and secret-looking files.
- English documentation tasks route to the low-cost provider.
- Git patch analysis uses `git apply --numstat -z` instead of textual `+++ b/`
  parsing, including ignored files created by a patch.
- Project YAML cannot override trusted Codex executable command settings.
- `GROQ_API_KEY` is not sent to untrusted, non-HTTPS, redirected, or
  project-overridden Groq URLs.

PHP syntax checks are implemented but skipped automatically when `php` is not installed.

