# Screen Reference

Inventory of screens that must stay visually consistent. Reference screenshots
belong in `ai-stack/design/screens/` once captured by the Visual QA engine.

| Screen | Purpose | Key components | Status |
|---|---|---|---|
| Character panel | avatar, stats, level progress | card, progress bar, tabs | planned |
| Inventory | item grid, categories, item actions | rarity cards, filters, equip/use actions | implemented in the PHP demo; browser checked at desktop/tablet/mobile |
| HUD / main play | navigation, quick actions, notifications | top bar, side nav, toast | planned |
| Chat | player messaging | panel, list, form | planned |
| Quest log | objectives and rewards | list, badge, table | planned |

Inventory reference captures from the demo are stored in `screens/`:

- [Desktop, 1440x900](screens/desktop.png)
- [Tablet, 768x1024](screens/tablet.png)
- [Mobile, 390x844](screens/mobile.png)

The mobile reference shows the equipped state and confirms that the filters and
cards fit the 390 px viewport. The browser report also records the interactive
equipment, filtering, and consumable checks.

## How to use this file

1. Before building a screen, check whether it already exists here.
2. Reuse the listed components instead of inventing near-duplicates.
3. After Visual QA, attach the captured screenshots and update the status.
4. If a screen changes its visual language, update `MASTER.md` first.
