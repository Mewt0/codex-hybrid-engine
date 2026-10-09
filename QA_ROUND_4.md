# QA Round 4

Status: completed with mock/local tests only. No paid API calls were made.

## Fixed

- Project YAML can no longer remove mandatory protected paths such as `.env`.
- Project YAML can no longer grant cloud context permissions by itself. Trusted user configuration may allow files; project configuration may only narrow that list.
- Ignored directories are expanded into individual file changes with a conservative scan limit. Oversized or unsupported ignored change sets fail closed.
- Codex provider now runs with a minimal environment and does not forward provider API keys such as `GROQ_API_KEY` or `OPENAI_API_KEY`.
- Groq and Codex integrations remain unverified against live services in this QA round.

## Verification

```text
python -m pytest -q
50 passed
```

Additional probes confirmed:

- symlink writes are blocked before agent execution;
- ignored `.env` and nested ignored token files are detected;
- Groq error bodies are redacted;
- Codex command hijack through project-local `PATH` remains blocked.

## Remaining Limits

Agent execution is still a program-level workflow, not an OS sandbox. A trusted Codex CLI or other agent process can still perform filesystem operations outside the project if the operating system permits it. Use container or OS-level sandboxing before running untrusted agents.
