---
name: browser-testing
description: Verify the interface in a real browser, not in the source code.
triggers: [browser, playwright, screenshot, responsive, visual, скриншот, браузер, адаптив]
---
# Browser testing

Code that renders is not proven until it was opened in a browser at the target
viewports.

## Procedure

1. Start the application the same way a developer would and note the URL.
2. For each changed screen, capture the three reference viewports:
   mobile 390x844, tablet 768x1024, desktop 1440x900.
3. Perform the primary user action end to end (click, submit, wait for result).
4. Collect console errors and failed network requests — a 500 or an uncaught
   exception fails the task even if the screen looks right.
5. Check the states that are easy to forget: empty, loading, error, disabled.
6. Save screenshots and reference them in the task result.

## What counts as a defect

- Overlapping or clipped elements, content hidden behind bars.
- Horizontal scrolling on a phone-width viewport.
- Text baked into images or below readable size.
- Controls smaller than 44x44 px, or hover-only affordances.
- Focus that cannot be reached with the keyboard.
- Animations that ignore `prefers-reduced-motion`.

## Honesty rule

If the environment cannot run a browser, report the check as NOT RUN with the
reason. Never describe an unexecuted visual check as passing.
