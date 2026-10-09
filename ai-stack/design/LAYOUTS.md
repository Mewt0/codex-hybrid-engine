# Layouts

## Breakpoints

| Name | Width | Target |
|---|---|---|
| mobile | 390 x 844 | phone portrait |
| tablet | 768 x 1024 | tablet portrait |
| desktop | 1440 x 900 | primary play surface |

## Game screen composition

```text
+--------------------------------------------------+
| top bar: character, currency, notifications      |
+------------------+-------------------------------+
| left navigation  | main content area             |
| (collapsible)    | (inventory / map / quests)    |
+------------------+-------------------------------+
| bottom bar: quick actions, chat toggle           |
+--------------------------------------------------+
```

## Rules

- Main content is the only scroll container between the bars.
- Left navigation collapses to icons below 1024 px and to a drawer below 640 px.
- HUD elements never overlap the safe area of the content on mobile.
- Grid: 12 columns desktop, 8 tablet, 4 mobile, gutter 16 px / 12 px.
- No horizontal page scrolling at 390 px width, ever.
- Empty states always explain the next useful action.
