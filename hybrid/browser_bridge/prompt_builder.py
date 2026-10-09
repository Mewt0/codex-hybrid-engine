from __future__ import annotations

from .providers.base import BrowserPrompt

ANSWER_FORMAT = """## SUMMARY
<what you changed and why, 2-5 sentences>

## FILES
- relative/path.php — what changes in this file

## PATCH
```diff
<unified diff produced with `diff -u` / `git diff` semantics, or the single word: none>
```

## CHECKS
- <checks that should pass after applying this change>

## LIMITATIONS
- <anything you could not verify or that needs a human decision>
"""

REVIEW_FORMAT = """## VERDICT
<approve / approve with changes / reject, one line>

## ISSUES
- <file:line — concrete problem, impact, minimal fix>

## PATCH
```diff
<only if you propose corrections, otherwise: none>
```

## LIMITATIONS
- <what you could not judge from the provided material>
"""

NO_ACCESS_NOTICE = """IMPORTANT — how your answer is used:
- You have NO access to the local filesystem, no terminal, no browser and no database.
- Do not ask to run commands. If you need a file you were not given, say which file and why.
- Everything you write is reviewed by a human and applied as a patch by a separate tool.
- Return the answer in the exact format below and nothing after it."""


class PromptBuilder:
    """Turns a Context Pack into one self-contained web-chat request."""

    def __init__(self, settings, context_builder):
        self.settings = settings
        self.context_builder = context_builder

    def build(self, task, context_pack, provider) -> BrowserPrompt:
        text = "\n\n".join(
            part
            for part in (
                self._header(task, context_pack, provider),
                self._project_context(context_pack),
                self._design(context_pack),
                self._skills(context_pack),
                self._files(context_pack),
                self._rules(),
                NO_ACCESS_NOTICE,
                "REQUIRED ANSWER FORMAT\n\n" + ANSWER_FORMAT,
            )
            if part
        )
        return BrowserPrompt(text=text, provider=provider.name, url=provider.url, notes=provider.notes())

    def build_review(self, task, context_pack, provider, first_solution: str) -> BrowserPrompt:
        text = "\n\n".join(
            part
            for part in (
                "# INDEPENDENT REVIEW REQUEST",
                self._header(task, context_pack, provider),
                self._project_context(context_pack),
                self._skills(context_pack),
                self._rules(),
                "# FIRST SOLUTION UNDER REVIEW\n\n" + self._clip(first_solution),
                NO_ACCESS_NOTICE,
                "REQUIRED ANSWER FORMAT\n\n" + REVIEW_FORMAT,
            )
            if part
        )
        return BrowserPrompt(text=text, provider=provider.name, url=provider.url, notes=provider.notes())

    # -- sections -----------------------------------------------------------

    def _header(self, task, context_pack, provider) -> str:
        stack = self.settings.raw.get("ai_stack", {}).get("stack_description") or (
            "legacy PHP backend, plain JavaScript, MySQL, HTML and CSS. "
            "No framework, no build step, no TypeScript."
        )
        return "\n".join(
            [
                "# TASK FOR A CODING MODEL",
                f"Task id: {task.task_id}",
                f"Work profile: {context_pack.profile}",
                f"Target project stack: {stack}",
                "",
                "## Request",
                task.description,
            ]
        )

    def _project_context(self, context_pack) -> str:
        body = context_pack.sections.get("project_context")
        return "# PROJECT CONTEXT\n\n" + body if body else ""

    def _design(self, context_pack) -> str:
        body = context_pack.sections.get("design")
        return "# DESIGN SYSTEM (follow it, do not invent a new look)\n\n" + body if body else ""

    def _skills(self, context_pack) -> str:
        if not context_pack.skills:
            return ""
        blocks = "\n\n".join(f"## Skill: {skill.name}\n\n{skill.body}" for skill in context_pack.skills)
        return "# REQUIRED SKILLS\n\n" + blocks

    def _files(self, context_pack) -> str:
        if not context_pack.files:
            return "# PROJECT FILES\n\nNo project files were attached to this request. Ask for what you need."
        blocks = "\n\n".join(f"### FILE: {rel}\n\n```\n{content}\n```" for rel, content in context_pack.files)
        return "# PROJECT FILES (read-only context)\n\n" + blocks

    def _rules(self) -> str:
        return "\n".join(
            [
                "# PROJECT RULES",
                "",
                "- Keep backward compatibility: do not rename or remove existing public functions,",
                "  do not change the response shape of existing endpoints, do not rewrite working code.",
                "- Legacy PHP: stay within the PHP version the file already targets.",
                "- Security: parameterize every SQL value, escape all output, check session and ownership",
                "  server-side, never trust an id coming from the browser.",
                "- Plain JavaScript with fetch: handle errors, prevent double submission, keep DOM updates",
                "  in one place per action.",
                "- Accessibility: real buttons, visible focus, 44x44 px minimum hit area, no colour-only meaning.",
                "- Responsive: must hold at 390 px, 768 px and 1440 px widths, no horizontal scrolling.",
                "- Do not add dependencies, frameworks or build steps.",
            ]
        )

    def _clip(self, text: str) -> str:
        limit = int(self.settings.raw.get("context", {}).get("max_response_chars", 30000))
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... [truncated by hybrid engine]\n"
