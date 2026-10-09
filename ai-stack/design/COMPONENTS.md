# Components

Every component below states its states, keyboard behaviour and the design
tokens it must use. New components follow the same shape.

## Button

- Variants: `primary` (accent), `secondary` (surface + border), `ghost`, `danger`.
- States: default, hover, active, focus-visible, disabled, loading.
- Minimum hit area 44x44 px; focus ring uses `--color-accent-strong` at 2 px.
- Loading keeps the label width stable and disables double submission.
- Never rely on hover alone to reveal an action.

## Card (item, character, quest)

- Structure: media, title, meta line, actions.
- Hover lifts by 2 px and brightens the border; no layout shift on hover.
- Rarity is expressed with a left accent bar plus a text label, not colour only.

## Panel

- Uses `--color-surface`, 1 px border, 12 px radius, 16-24 px padding.
- Header is sticky when the panel body scrolls.

## Modal

- Traps focus, `Esc` closes, backdrop click closes only for non-destructive modals.
- Destructive confirmations name the action in the confirm button.

## Table

- Numeric columns are right-aligned with tabular numerals.
- Row height minimum 40 px; zebra striping uses `--color-surface-raised` at 40%.
- On narrow screens the table collapses into stacked label/value rows.

## Form

- Label above input; errors directly under the field, never in a toast only.
- Validation runs on blur and on submit, not on every keystroke.
- Required fields are marked in text, not by colour.

## Toast / notification

- Appears top-right on desktop, bottom-centre on mobile.
- Auto-dismiss after 5 s, pause on hover/focus, dismissible by keyboard.
- Errors stay until dismissed.
