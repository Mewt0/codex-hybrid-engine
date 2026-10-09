---
name: beautiful-game-ui
description: Build distinctive, coherent game interfaces instead of templated defaults.
triggers: [ui, interface, design, css, layout, dashboard, panel, hud, инвентар, интерфейс, дизайн, вёрстка, верстка]
---
# Beautiful game UI

Use when the task changes how the game looks or feels.

## Method

1. Read `ai-stack/design/MASTER.md` and the specific design file for the area
   you are touching (colors, typography, components, layouts, animations).
2. Name the visual direction in one sentence before writing code.
3. Reuse existing components from `COMPONENTS.md`; introduce a new component
   only when no existing one fits, and then document it in the same file.
4. Build the desktop layout first, then make it collapse for tablet and mobile.
5. Finish with states: hover, focus-visible, active, disabled, loading, empty,
   error. A screen without states is not finished.

## Anti-patterns

- Purple-blue gradient on everything, glassmorphism without reason.
- Centered everything with default system font and pure `#fff` text on `#000`.
- Icon-only buttons without accessible labels.
- Decorative animation on interactive controls.
- Mixing two unrelated visual styles in one screen.
