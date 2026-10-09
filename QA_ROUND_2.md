# QA Round 2

## Fixes

- Git porcelain v1 NUL records preserve rename/copy source and destination.
- Untracked files are enumerated individually, including nested directories.
- Binary patches use Git's binary format; generated patches disable rename
  compression so source deletions cannot disappear from validation.
- Disabled providers are rejected before construction/execution, including
  explicit overrides. Dry-run remains available without executing providers.
- package.json and composer.json are parsed as JSON. New dependency entries
  and version changes are blocked by default; description-only edits pass.
- Apply replays the stored, hash-checked patch in a disposable repository and
  repeats path, dependency and syntax checks before touching the project.
- Deleted files are not passed to syntax checkers. Missing PHP is SKIP.
- Symlink changes are rejected; failed path checks do not run syntax tools.

## Cloud context

Groq receives only files explicitly listed in `context.allowed_files`:

```yaml
context:
  allowed_files:
    - app.js
    - src/chat.php
```

The default list is empty. Paths are exact project-relative names, not globs.
Use `hybrid run "task" --provider groq --dry-run` to preview selected paths.
Configuration directories, .env variants, sensitive names, forbidden paths
and symlinks are excluded even when explicitly listed. The total file context
is limited to 80,000 bytes. Inspect allowed files and task descriptions yourself:
these checks cannot prove the absence of embedded credentials. Agent providers
have broader filesystem access than model context lists.

## Reproduction

Executed result: 33 passed, 0 failed, 0 skipped (2.65 seconds).
`compileall` completed successfully. Missing-PHP behavior was explicitly
simulated and verified as SKIP, not a successful PHP syntax check.

```sh
python -m pytest -q
python -m pytest -v tests/test_security_regressions.py
python -m compileall -q hybrid
```

The audit's original test attachment was not available. The new regression
module reconstructs its five scenarios and adds adjacent cases. Its parametrized
FAST/SAFE tests demonstrate isolated creation, patch review, refusal without
confirmation, and confirmed application in temporary Git repositories.

## Remaining limitations

Git worktrees and temporary copies are not OS security sandboxes. Path checks,
allowlists, dependency policy and patch hashes are application-level controls.
No new OS-level filesystem confinement was added. A malicious agent running as
the same user could access other paths or shared Git metadata. Concurrent hostile
filesystem mutation is not prevented by these checks.

Copy provenance cannot be inferred when a provider creates a new file with the
same contents without Git reporting a copy. Dependency policy covers declared
JSON manifest sections, not arbitrary install scripts or all lockfile semantics.
SAFE uses committed HEAD; dirty user files are preserved, and apply refuses a
dirty main worktree. Temporary validation directories are retained with tasks.

Codex and Groq real integrations were not exercised in this round. Provider
behavior was tested with local mocks; no paid calls were made. DeepSeek Harness
remains disabled and is not a verified working integration.
