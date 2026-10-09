from __future__ import annotations


class BrowserBridgeError(RuntimeError):
    """Raised for any expected browser-bridge failure (never for control flow)."""


class ResponseAlreadyImported(BrowserBridgeError):
    """A response was already imported and validated for this task."""


class BrowserProviderError(BrowserBridgeError):
    """The requested browser provider is unknown or cannot be used."""
