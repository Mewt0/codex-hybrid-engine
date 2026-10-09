# Installation

Target environment: Windows with WSL2 Ubuntu.

```bash
cd codex-hybrid-engine
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
hybrid doctor
```

Optional tools:

- Codex CLI for `--provider codex`.
- PHP for `php -l` checks.
- Node.js for JavaScript syntax checks.
- `GROQ_API_KEY` for Groq calls.

No NVIDIA API or local large LLM is required.

