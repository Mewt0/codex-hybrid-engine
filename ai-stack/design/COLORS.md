# Colors

## Core palette

| Token | Value | Use |
|---|---|---|
| `--color-bg` | `#0e1116` | application background |
| `--color-surface` | `#161b23` | panels, cards |
| `--color-surface-raised` | `#1e2530` | modals, popovers |
| `--color-border` | `#2b3441` | separators |
| `--color-accent` | `#d8a13a` | primary actions, gold |
| `--color-accent-strong` | `#f0bc58` | hover / active accent |
| `--color-text` | `#e8e3d9` | body text (parchment) |
| `--color-text-muted` | `#a4a095` | secondary text |

## Semantic states

| State | Value | Notes |
|---|---|---|
| success | `#5fbf7a` | confirmations, item gained |
| warning | `#e0a63c` | low durability, limits |
| danger | `#d9604f` | destructive actions, errors |
| info | `#5b9bd5` | neutral notices |

## Rules

- Accent colour is reserved for the primary action of a screen.
- Never encode meaning by colour alone: pair it with an icon or label.
- Disabled controls use `--color-text-muted` at 40% opacity, never pure grey.
- Check every new pair against WCAG AA before merging.
