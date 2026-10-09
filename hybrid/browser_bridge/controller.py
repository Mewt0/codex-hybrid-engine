from __future__ import annotations

from pathlib import Path

from hybrid.context import ContextBuilder, choose_profile
from hybrid.tasks import TaskRecord, TaskStatus
from .prompt_builder import PromptBuilder
from .providers import BrowserProviderError, get_provider, provider_names
from .response_parser import ResponseParser
from .sessions import BrowserBridgeError, BrowserTask, BrowserTaskStore, ResponseAlreadyImported


class BrowserBridge:
    """Relay workflow: engine prepares, the human talks to the web chat, engine imports.

    The bridge owns no network code and no credentials. It reuses the existing
    Task Controller for validation, quality gates, review and apply, so a
    browser task travels through exactly the same safety path as an API task.
    """

    TASK_MODE = "browser"

    def __init__(self, settings, controller, store: BrowserTaskStore | None = None,
                 context_builder: ContextBuilder | None = None,
                 prompt_builder: PromptBuilder | None = None,
                 parser: ResponseParser | None = None):
        self.settings = settings
        self.controller = controller
        self.store = store or BrowserTaskStore(settings.data_dir)
        self.context_builder = context_builder or ContextBuilder(settings)
        self.prompt_builder = prompt_builder or PromptBuilder(settings, self.context_builder)
        self.parser = parser or ResponseParser()

    # -- discovery ----------------------------------------------------------

    def provider_names(self) -> list[str]:
        return provider_names()

    def provider_status(self) -> list[dict]:
        report = []
        for name in provider_names():
            provider = get_provider(name)
            ok, detail = provider.available()
            report.append(
                {
                    "name": provider.name,
                    "display_name": provider.display_name,
                    "url": provider.url,
                    "mode": provider.mode,
                    "available": ok,
                    "detail": detail,
                }
            )
        return report

    # -- prepare ------------------------------------------------------------

    def prepare(self, description: str, provider: str, profile: str | None = None) -> BrowserTask:
        if not description or not description.strip():
            raise BrowserBridgeError("Task description must not be empty")
        chosen_provider = get_provider(provider)
        chosen_profile = choose_profile(description, profile)

        record = TaskRecord.new(description, self.TASK_MODE, chosen_provider.name, "medium", self.settings.root)
        record.profile = chosen_profile
        record.source = "browser_bridge"
        record.status = TaskStatus.WAITING_FOR_USER.value
        record.artifact_dir = str(self.controller._artifact_dir(record.task_id))

        pack = self.context_builder.build(record, chosen_profile)
        record.skills = pack.skill_names()

        browser_task = BrowserTask.new(chosen_provider.name, description, chosen_profile, chosen_provider.url)
        browser_task.engine_task_id = record.task_id
        browser_task.skills = list(record.skills)

        prompt = self.prompt_builder.build(record, pack, chosen_provider)
        engine_prompt_path = self.controller._artifact_dir(record.task_id) / "prompt.md"
        engine_prompt_path.write_text(prompt.text, encoding="utf-8", newline="\n")
        store_prompt_path = self.store.write_prompt(browser_task.task_id, prompt.text)

        record.prompt_path = str(store_prompt_path)
        browser_task.prompt_path = str(store_prompt_path)
        self.controller.store.save(record)
        self.store.save(browser_task)
        return browser_task

    # -- accessors ----------------------------------------------------------

    def prompt(self, task_id: str) -> str:
        self._require(task_id)
        return self.store.read_prompt(task_id)

    def open(self, task_id: str) -> str:
        task = self._require(task_id)
        provider = get_provider(task.provider)
        return provider.open_url()

    def task(self, task_id: str) -> BrowserTask:
        return self._require(task_id)

    def history(self) -> list[BrowserTask]:
        return self.store.history()

    def cancel(self, task_id: str) -> BrowserTask:
        task = self._require(task_id)
        if task.status in {TaskStatus.READY_FOR_REVIEW.value, TaskStatus.APPLIED.value}:
            raise BrowserBridgeError("Task already produced a reviewed patch; cancel it as a hybrid task instead")
        return self.store.cancel(task_id)

    # -- import -------------------------------------------------------------

    def import_response(
        self,
        task_id: str,
        text: str,
        force: bool = False,
        conversation_url: str | None = None,
        prompt_sha256: str | None = None,
        prompt_source: str | None = None,
        partial: bool = False,
    ) -> TaskRecord:
        browser_task = self._require(task_id)
        if not text or not text.strip():
            raise BrowserBridgeError("Imported response is empty")

        record = self._record(browser_task)
        guarded_statuses = {TaskStatus.READY_FOR_REVIEW.value, TaskStatus.APPLIED.value}
        if record.status in guarded_statuses and not force:
            raise ResponseAlreadyImported(
                f"{record.task_id} already has a validated result; re-import with --force to replace it"
            )

        # Provenance is written only *after* the import is accepted, so a refused
        # or failed import can never relabel a task with a prompt that produced
        # nothing.
        if conversation_url:
            browser_task.conversation_url = conversation_url
        if prompt_sha256:
            browser_task.prompt_sha256 = prompt_sha256
        if prompt_source:
            browser_task.prompt_source = prompt_source
        if conversation_url or prompt_sha256 or prompt_source:
            self.store.save(browser_task)

        overwrite = bool(record.patch_sha256 or record.response_path)
        response_path, digest = self.store.import_response(task_id, text, force=force)
        parsed = self.parser.parse(record.task_id, text)

        record.response_path = str(response_path)
        # Use the digest of the normalized text that was actually stored, so the
        # review payload and the store always agree.
        record.response_sha256 = digest
        record.import_count += 1
        record.analysis = parsed.summary() or None
        record.output = record.analysis
        if overwrite:
            parsed.warnings.append("A previously imported result was replaced because --force was used.")
            record.patch_sha256 = None
            record.changed_files = []
            record.checks = {}
        if partial:
            # The automation could not prove the answer finished, so the text may
            # be truncated. That must be visible in the review, not just in the
            # artifacts, because a partial patch can still look plausible.
            parsed.warnings.append(
                "The browser automation could not prove the answer finished streaming; "
                "this response may be truncated (imported because --allow-partial was passed)."
            )

        if not parsed.is_patch:
            record.status = TaskStatus.WAITING_FOR_USER.value
            record.error = None
            self.controller.store.save(record)
            self.store.write_review(task_id, self._payload(record, parsed, "analysis_only", applied=False))
            return record
        path_checks = self.parser.validate_patch(parsed, self.settings, self.settings.root)
        hard_failures = [check for check in path_checks if check.status == "FAIL"]
        for check in parsed.warnings:
            path_checks.append(self._warn(check))
        if hard_failures:
            record.status = TaskStatus.FAILED.value
            record.error = "; ".join(f"{check.name}: {check.detail}" for check in hard_failures)
            record.checks = {check.name: {"status": check.status, "detail": check.detail} for check in path_checks}
            self.controller.store.save(record)
            self.store.write_review(task_id, self._payload(record, parsed, "rejected", applied=False))
            return record

        record.base_commit = self._base_commit()
        record.base_ref = record.base_commit
        self.controller._save_patch(record, parsed.patch or "")
        validation = self.controller._validate_patch_on_temp(record, parsed.patch or "")
        for check in validation:
            path_checks.append(check)
        record.checks = {check.name: {"status": check.status, "detail": check.detail} for check in path_checks}
        failed = self.controller._has_fail(validation)
        record.status = TaskStatus.FAILED.value if failed else TaskStatus.READY_FOR_REVIEW.value
        record.error = "Quality validation failed before review" if failed else None
        self.controller.store.save(record)
        self.store.write_review(task_id, self._payload(record, parsed, "patch_validated", applied=False))
        return record

    def review_payload(self, task_id: str) -> dict:
        browser_task = self._require(task_id)
        record = self._record(browser_task)
        return {
            "browser_task_id": browser_task.task_id,
            "engine_task_id": record.task_id,
            "provider": browser_task.provider,
            "profile": browser_task.profile,
            "status": record.status,
            "skills": record.skills,
            "changed_files": record.changed_files,
            "checks": record.checks,
            "error": record.error,
            "prompt_path": browser_task.prompt_path,
            "prompt_sha256": browser_task.prompt_sha256,
            "prompt_source": browser_task.prompt_source,
            "conversation_url": browser_task.conversation_url,
            "response_path": record.response_path,
            "import_count": record.import_count,
            "apply_command": f"hybrid apply {record.task_id} --yes",
        }

    def diff(self, task_id: str) -> str:
        browser_task = self._require(task_id)
        record = self._record(browser_task)
        return self.controller.diff(record.task_id)

    # -- review request for a second provider -------------------------------

    def prepare_review(self, task_id: str, reviewer: str | None = None) -> BrowserTask:
        source = self._require(task_id)
        record = self._record(source)
        if not record.response_path:
            raise BrowserBridgeError("Import the first answer before requesting a review")
        first_solution = Path(record.response_path).read_text(encoding="utf-8")

        reviewer_name = reviewer or ("chatgpt_web" if source.provider != "chatgpt_web" else "deepseek_web")
        provider = get_provider(reviewer_name)
        pack = self.context_builder.build(record, record.profile or None)
        prompt = self.prompt_builder.build_review(record, pack, provider, first_solution)

        review_task = BrowserTask.new(provider.name, f"Independent review of {source.task_id}", record.profile or "review", provider.url)
        review_task.engine_task_id = record.task_id
        self.store.write_prompt(review_task.task_id, prompt.text)
        self.store.save(review_task)
        return review_task

    # -- internals ----------------------------------------------------------

    def _require(self, task_id: str) -> BrowserTask:
        return self.store.get(task_id)

    def _record(self, browser_task: BrowserTask) -> TaskRecord:
        if not browser_task.engine_task_id:
            raise BrowserBridgeError(f"{browser_task.task_id} has no linked engine task")
        return self.controller.store.get(browser_task.engine_task_id)

    def _base_commit(self) -> str | None:
        from hybrid.execution import worktree

        worktree.ensure_repo(self.settings.root)
        return worktree.base_commit(self.settings.root)

    def _warn(self, message: str) -> object:
        from hybrid.quality.checks import CheckResult

        return CheckResult("Warning", "WARN", message)

    def _payload(self, record: TaskRecord, parsed, stage: str, applied: bool) -> dict:
        return {
            "stage": stage,
            "status": record.status,
            "provider": record.provider,
            "profile": record.profile,
            "skills": record.skills,
            "response_sha256": parsed.response_sha256,
            "is_patch": parsed.is_patch,
            "files_in_patch": parsed.files,
            "changed_files": record.changed_files,
            "checks": record.checks,
            "warnings": parsed.warnings,
            "limitations": parsed.section("LIMITATIONS"),
            "summary": parsed.summary(),
            "applied": applied,
            "apply_command": f"hybrid apply {record.task_id} --yes",
        }
