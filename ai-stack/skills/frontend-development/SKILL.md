---
name: frontend-development
description: Plain HTML/CSS/JS implementation rules for the game interface.
triggers: [javascript, js, html, css, ajax, form, fetch, animation, фронтенд, кнопка, анимация]
---
# Frontend development

Target stack is plain HTML, CSS and JavaScript talking to PHP endpoints.
Do not introduce React, Vue, Tailwind or a build step unless the task says so.

## Rules

- Use `fetch` with explicit error handling; never assume a 200 response.
- Disable the triggering control while a request is in flight to prevent
  double submission; re-enable it in `finally`.
- Update the DOM through a single function per action so state stays consistent.
- Keep CSS in the project's existing files; use custom properties for tokens.
- Scope selectors to the component; no global element selectors.
- Never build HTML from unsanitized user input (no `innerHTML` with raw strings).
- Accessibility: real `button`/`a` elements, labels tied to inputs, visible
  focus, `aria-live` for async result messages.

## Verification before claiming done

- The action works with the keyboard only.
- A failed request shows a readable message, not a silent no-op.
- Layout holds at 390 px and 1440 px widths.
