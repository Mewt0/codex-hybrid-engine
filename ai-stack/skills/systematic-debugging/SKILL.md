---
name: systematic-debugging
description: Find the real cause before changing code.
triggers: [bug, error, broken, crash, debug, не работает, ошибка, баг, падает]
---
# Systematic debugging

Never patch a symptom. Reproduce, isolate, prove, then fix.

## Loop

1. **Reproduce** — the smallest input that shows the failure, written down.
2. **Observe** — the exact error text, stack trace or wrong value. No guessing.
3. **Isolate** — narrow by bisection: which layer, file, function, line.
4. **Hypothesize** — one sentence: "X fails because Y".
5. **Test the hypothesis** — a probe that fails if the hypothesis is wrong.
6. **Fix the cause** — the smallest change that removes the cause.
7. **Prove** — re-run the original reproduction plus a regression test.

## Rules

- Change one thing at a time.
- If three attempts fail, the model of the system is wrong: go back to step 2
  and gather evidence instead of trying another patch.
- Never silence an error (`try/except: pass`, `@`, blanket `catch`) to make a
  test pass.
- Distinguish "works on my machine" from "works": check paths, line endings,
  permissions, locale and environment variables explicitly.
- Write down what was ruled out; it prevents repeating the same dead end.
