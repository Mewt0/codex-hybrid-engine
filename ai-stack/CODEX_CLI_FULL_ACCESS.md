# Codex Full-Access Exception

Scope of the sandbox exception, layer by layer. Everything below was measured on
`codex-cli 0.162.0-alpha.2` on this machine; see `docs/MASTER_CONFORMITY_RESULT.md`
§ O.6 and § O.7 for the underlying `workspace-write` defect.

## 1. Direct Codex CLI

`danger-full-access` is allowed when the user explicitly requests full access for
that CLI session. Never combine it with `--dangerously-bypass-approvals-and-sandbox`.

Approval handling cannot be kept enabled in the non-interactive path. `codex exec`
has no `-a/--ask-for-approval` flag and reports `approval: never` regardless of
`-c approval_policy=...`; that flag exists only on the interactive `codex` command.
The rules that can actually be enforced are therefore:

- full access only on an explicit user request;
- never the bypass flag above.

## 2. Hybrid Engine Codex provider

The engine's Codex provider may also run with `danger-full-access`, but only when
the **trusted user config** — `~/.config/codex-hybrid-engine/settings.yaml`, or
`$XDG_CONFIG_HOME`/`$HYBRID_USER_CONFIG` when set — selects it:

```yaml
providers:
  codex:
    sandbox: danger-full-access
```

A project `config/settings.yaml` can never set this field.
`TRUSTED_PROVIDER_FIELDS["codex"]` is `{"enabled", "timeout_seconds"}`, so the value
is stripped and recorded in `sources["ignored_project_fields"]`.

`providers.codex.command` must point at the real Codex install directory. Codex
spawns `codex-code-mode-host.exe` and `codex-command-runner.exe` from its own
directory, so a lone copy of `codex.exe` fails with "the command runner failed to
start because its executable is missing" and writes nothing even with full access.

## 3. Delegated agents — unchanged

`CodexCliDelegate` accepts only `read-only` and `workspace-write`
(`ALLOWED_SANDBOXES` in `hybrid/integrations/codex_cli_delegate.py`) and never emits
`--dangerously-bypass-approvals-and-sandbox`. Recursive delegation stays disabled via
`HYBRID_INSIDE_AGENT`.

## 4. Why the exception exists, and when not to use it

`workspace-write` is broken on this machine: `codex-windows-sandbox-setup.exe`
cannot provision, so every command fails with
`helper_unknown_error: setup refresh had errors`. On a machine where
`workspace-write` works, prefer it and leave this exception unused.

Project changes still follow the Hybrid task lifecycle: propose a patch and apply it
with `hybrid apply <TASK-ID> --yes`. Do not commit or push.
