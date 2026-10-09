from __future__ import annotations

import json
import os
import time
from urllib.parse import urlparse
import urllib.error
import urllib.request
from .base import Provider, ProviderContext, ProviderError
from hybrid.tasks import TaskRecord, TaskResult


class GroqProvider(Provider):
    name = "groq"
    kind = "model"

    def __init__(self, config: dict, budget: dict):
        self.config = config
        self.budget = budget

    def available(self) -> tuple[bool, str]:
        ok, detail = self._validate_base_url()
        if not ok:
            return False, detail
        if not os.environ.get("GROQ_API_KEY"):
            return False, "GROQ_API_KEY is not set"
        return True, "configured"

    def list_models(self) -> tuple[bool, str]:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            return False, "GROQ_API_KEY is not set"
        ok, detail = self._validate_base_url()
        if not ok:
            return False, detail
        url = self.config.get("base_url", "").rstrip("/") + "/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        try:
            with self._opener().open(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            ids = [m.get("id", "") for m in data.get("data", [])]
            return True, ", ".join(sorted(filter(None, ids))[:40])
        except Exception:
            return False, "Groq model listing failed; response details redacted."

    def execute(self, task: TaskRecord, context: ProviderContext) -> TaskResult:
        start = time.monotonic()
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise ProviderError("GROQ_API_KEY is not set; no cloud call was made.")
        ok, detail = self._validate_base_url()
        if not ok:
            raise ProviderError(detail)
        if self.budget.get("allow_paid_api", False):
            raise ProviderError("Paid API use is disabled by policy in this MVP.")
        model = self.config.get("small_model")
        prompt = build_patch_prompt(task, context)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
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
                raise ProviderError(f"Groq API error {exc.code}; response details redacted.") from exc
            except TimeoutError as exc:
                if attempt < retries:
                    continue
                raise ProviderError("Groq API timeout") from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    continue
                raise ProviderError("Groq connection error; response details redacted.") from exc
        raise ProviderError("Groq request failed after retry limit")

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
        return payload["choices"][0]["message"]["content"]

    def _validate_base_url(self) -> tuple[bool, str]:
        base_url = str(self.config.get("base_url", "")).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https":
            return False, "Groq base_url must use HTTPS; GROQ_API_KEY was not sent."
        if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
            return False, "Groq base_url must be the canonical official endpoint; no request was made."
        if parsed.hostname != "api.groq.com":
            return False, "GROQ_API_KEY may only be sent to https://api.groq.com; no request was made."
        if parsed.path.rstrip("/") != "/openai/v1":
            return False, "Groq base_url must be https://api.groq.com/openai/v1; no request was made."
        return True, "official Groq endpoint"

    def _opener(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                raise ProviderError("Groq request redirected; GROQ_API_KEY was not forwarded.")

        return urllib.request.build_opener(NoRedirect)


def build_patch_prompt(task: TaskRecord, context: ProviderContext) -> str:
    files = []
    for path in context.target_files:
        rel = path.relative_to(context.project_dir)
        files.append(f"FILE: {rel}\n```\n{path.read_text(encoding='utf-8', errors='replace')[:12000]}\n```")
    return (
        "Return a unified diff patch only. Do not include secrets or unrelated files.\n"
        f"TASK:\n{task.description}\n\n"
        "RULES:\n- Preserve existing APIs.\n- Do not add dependencies.\n- Do not modify authentication unless explicitly requested.\n\n"
        + "\n\n".join(files)
    )

