from __future__ import annotations

from .base import BrowserPrompt, BrowserProvider


class ChatGptWebProvider(BrowserProvider):
    name = "chatgpt_web"
    display_name = "ChatGPT Web"
    url = "https://chatgpt.com"
    mode = "relay"

    def notes(self) -> list[str]:
        return [
            f"Open {self.url} and sign in with your own account.",
            "Select whichever model your account currently offers; the engine does not assume one.",
            "Paste the prepared prompt, send it and wait for the full answer.",
            "Copy the whole answer back with `hybrid browser import <TASK-ID> --file <path>`.",
        ]

    def prepare(self, task, context_pack, prompt_builder) -> BrowserPrompt:
        prompt = prompt_builder.build(task, context_pack, self)
        return BrowserPrompt(
            text=prompt.text,
            provider=self.name,
            url=self.url,
            notes=prompt.notes or self.notes(),
        )
