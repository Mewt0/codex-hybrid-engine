# Animations

## Allowed durations

| Token | Duration | Use |
|---|---|---|
| `--motion-instant` | 90 ms | hover, focus |
| `--motion-fast` | 160 ms | buttons, toggles, tooltips |
| `--motion-base` | 240 ms | panels, cards, dropdowns |
| `--motion-slow` | 400 ms | modals, screen transitions |

## Easing

- Enter: `cubic-bezier(0.16, 1, 0.3, 1)` (decelerate).
- Exit: `cubic-bezier(0.4, 0, 1, 1)` (accelerate), 30% shorter than enter.
- Loops (idle glow, loading): `ease-in-out`, never faster than 800 ms.

## Game effects

- Item gain / level up: scale 0.96 -> 1 with a single gold flash, max 400 ms.
- Damage numbers: rise 24 px and fade within 600 ms.
- Screen shake: maximum 3 px, must be disableable in settings.

## Rules

- Animate `transform` and `opacity`; avoid animating layout properties.
- Never animate more than two elements in a way that draws focus at once.
- No infinite animation on interactive controls.
- All motion is disabled under `@media (prefers-reduced-motion: reduce)` except
  functional feedback (loading spinners become static text).
- Animations never delay the user's next action.
