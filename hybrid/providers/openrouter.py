from __future__ import annotations

import json
import os
import time
from urllib.parse import urlparse
import urllib.error
import urllib.request
from .base import Provider, ProviderContext, ProviderError
from .groq import build_patch_prompt
from hybrid.tasks import TaskRecord, TaskResult


class OpenRouterProvider(Provider):
    """Optional OpenRouter provider (OpenAI-compatible API).

    Mirrors the Groq provider on purpose: same key handling, same refusal to
    follow redirects, same budget policy. It is disabled in the default
    configuration so that turning Groq off - or OpenRouter on - never breaks
    the other provider.
    """

    name = "openrouter"
    kind = "model"

    def __init__(self, config: dict, budget: dict):
        self.config = config
        self.budget = budget

    def available(self) -> tuple[bool, str]:
        ok, detail = self._validate_base_url()
        if not ok:
            return False, detail
        if not os.environ.get("OPENROUTER_API_KEY"):
            return False, "OPENROUTER_API_KEY is not set"
        return True, "configured"

    def execute(self, task: TaskRecord, context: ProviderContext) -> TaskResult:
        start = time.monotonic()
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ProviderError("OPENROUTER_API_KEY is not set; no cloud call was made.")
        ok, detail = self._validate_base_url()
        if not ok:
            raise ProviderError(detail)
        if self.budget.get("allow_paid_api", False):
            raise ProviderError("Paid API use is disabled by policy in this MVP.")
        body = {
            "model": self.config.get("small_model"),
            "messages": [{"role": "user", "content": build_patch_prompt(task, context)}],
            "temperature": 0.1,
        }
        retries = int(self.budget.get("max_retries", 1))
        for attempt in range(retries + 1):
            try:
                output = self._post_chat(body, key)
                return TaskResult(task.task_id, self.name, "ok", time.monotonic() - start, output=output)
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < retries:
                    retry_after = int(exc.headers.get("Retry-After", "1"))
                    time.sleep(min(retry_after, 30))
                    continue
                raise ProviderError(f"OpenRouter API error {exc.code}; response details redacted.") from exc
            except TimeoutError as exc:
                if attempt < retries:
                    continue
                raise ProviderError("OpenRouter API timeout") from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    continue
                raise ProviderError("OpenRouter connection error; response details redacted.") from exc
        raise ProviderError("OpenRouter request failed after retry limit")

    def _post_chat(self, body: dict, key: str) -> str:
        url = self.config.get("base_url", "").rstrip("/") + "/chat/completions"
        ok, detail = self._validate_base_url()
        if not ok:
            raise ProviderError(detail)
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with self._opener().open(req, timeout=int(self.config.get("timeout_seconds", 60))) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("OpenRouter returned an invalid response.") from exc

    def _validate_base_url(self) -> tuple[bool, str]:
        base_url = str(self.config.get("base_url", "")).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https":
            return False, "OpenRouter base_url must use HTTPS; OPENROUTER_API_KEY was not sent."
        if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
            return False, "OpenRouter base_url must be the canonical official endpoint; no request was made."
        if parsed.hostname != "openrouter.ai":
            return False, "OPENROUTER_API_KEY may only be sent to https://openrouter.ai; no request was made."
        if parsed.path.rstrip("/") != "/api/v1":
            return False, "OpenRouter base_url must be https://openrouter.ai/api/v1; no request was made."
        return True, "official OpenRouter endpoint"

    def _opener(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ProviderError("OpenRouter request redirected; OPENROUTER_API_KEY was not forwarded.")

        return urllib.request.build_opener(NoRedirect)
