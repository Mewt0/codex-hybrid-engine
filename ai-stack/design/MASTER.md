# Design System

Design Memory for the game UI. These files are the single source of visual
truth for every model working on the project.

## Rule zero

A new interface must continue the existing design system. If the user asks for a
new visual direction, update this design system first, then the components that
depend on it. Never let two agents invent two different looks.

## Files

| File | Contents |
|---|---|
| `COLORS.md` | palette, semantic states, contrast requirements |
| `TYPOGRAPHY.md` | font stack, scale, readability rules |
| `COMPONENTS.md` | buttons, cards, panels, modals, tables, forms, toasts |
| `LAYOUTS.md` | HUD, menus, side panels, screen composition |
| `ANIMATIONS.md` | allowed transitions, durations, reduced-motion rules |
| `SCREEN_REFERENCE.md` | inventory of existing screens and reference shots |

## Baseline direction

Dark fantasy game UI: deep slate surfaces, warm gold accent for actions, muted
parchment text, high contrast on interactive elements, generous spacing,
subtle depth instead of heavy borders.

## Non-negotiable quality bars

- Interactive controls: minimum 44x44 px hit area.
- Body text contrast >= 4.5:1, large text >= 3:1.
- No horizontal scrolling at 390 px width.
- Focus states are always visible for keyboard users.
- Motion respects `prefers-reduced-motion: reduce`.
