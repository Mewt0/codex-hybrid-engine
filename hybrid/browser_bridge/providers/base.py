from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..errors import BrowserProviderError


@dataclass(frozen=True)
class BrowserPrompt:
    text: str
    provider: str
    url: str
    notes: list[str] = field(default_factory=list)


class BrowserProvider(ABC):
    """A web chat that a human relays messages to.

    The engine never talks to the site itself: it prepares a prompt, opens the
    official page in the user's own browser and later imports whatever the user
    pastes back. No cookies, tokens or profile data are read or stored.
    """

    name: str = "browser"
    display_name: str = "Web chat"
    url: str = ""
    mode: str = "relay"

    def available(self) -> tuple[bool, str]:
        if not self.url.startswith("https://"):
            return False, "official HTTPS URL is not configured"
        return True, "relay mode: the user signs in and pastes the answer manually"

    def notes(self) -> list[str]:
        return [
            f"Open {self.url} and sign in with your own account.",
            "Paste the prepared prompt, send it and wait for the full answer.",
            "Copy the whole answer back with `hybrid browser import <TASK-ID> --file <path>`.",
        ]

    def open_url(self) -> str:
        import webbrowser

        if not self.url.startswith("https://"):
            raise BrowserProviderError(f"{self.name}: refusing to open a non-HTTPS URL")
        try:
            opened = webbrowser.open(self.url, new=2)
        except Exception as exc:  # pragma: no cover - depends on the host browser
            raise BrowserProviderError(f"Could not open a browser: {exc}") from exc
        if not opened:
            raise BrowserProviderError(
                f"Could not open {self.url} automatically. Open it manually and continue with the next step."
            )
        return self.url

    @abstractmethod
    def prepare(self, task, context_pack, prompt_builder) -> BrowserPrompt:
        raise NotImplementedError
