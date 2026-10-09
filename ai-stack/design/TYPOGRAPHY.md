# Typography

## Font stack

- UI: `"Inter", "Segoe UI", system-ui, sans-serif`
- Numerals / stats: same stack with `font-variant-numeric: tabular-nums`
- Display (game titles): `"Cinzel", "Georgia", serif`

## Scale

| Token | Size / line-height | Use |
|---|---|---|
| `--text-xs` | 12 / 16 | labels, badges |
| `--text-sm` | 14 / 20 | secondary text |
| `--text-base` | 16 / 24 | body |
| `--text-lg` | 20 / 28 | card titles |
| `--text-xl` | 26 / 32 | section headings |
| `--text-2xl` | 34 / 40 | screen titles |

## Rules

- Body copy is never below 14 px; in-game notifications never below 13 px.
- Maximum 2 font families per screen.
- Headings use weight 600; body uses 400. Avoid faux-bold.
- Line length stays within 75 characters for prose blocks.
- Numbers in stats and inventories always use tabular numerals so columns align.
