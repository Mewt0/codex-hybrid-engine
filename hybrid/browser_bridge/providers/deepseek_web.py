from __future__ import annotations

from .base import BrowserPrompt, BrowserProvider


class DeepSeekWebProvider(BrowserProvider):
    name = "deepseek_web"
    display_name = "DeepSeek Web"
    url = "https://chat.deepseek.com"
    mode = "relay"

    def prepare(self, task, context_pack, prompt_builder) -> BrowserPrompt:
        prompt = prompt_builder.build(task, context_pack, self)
        return BrowserPrompt(
            text=prompt.text,
            provider=self.name,
            url=self.url,
            notes=prompt.notes or self.notes(),
        )
