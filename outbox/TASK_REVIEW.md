# TASK: Независимое ревью Browser AI Bridge

Прикрепи сначала `outbox/00_BOILERPLATE.md`, потом это задание.

## Ситуация

Мост к веб-чатам уже написан и проходит 106 тестов. Твоя работа — **не писать
всё заново**, а провести независимое ревью кода и вернуть **только точечные
исправления** в формате diff, если они реально нужны.

Ниже — фактический код модулей. Найди ошибки, риски и несоответствия
требованиям безопасности. Если код корректен — так и напиши, не выдумывай
проблемы ради объёма.

## Требования, которые код обязан выполнять

1. Никаких сетевых запросов к сайтам ИИ: только `webbrowser.open(<official https url>)`.
2. Никаких cookies, токенов, паролей и данных профиля браузера: не читать, не хранить.
3. Контекст ограничен доверенным `context.allowed_files`; `.env`, `.hybrid/`,
   `config/secrets/*`, `tests/protected/*`, выход за пределы проекта — запрещены.
4. Ответ модели разбирается по секциям `## SUMMARY / ## FILES / ## PATCH / ## CHECKS / ## LIMITATIONS`.
5. Патч применяется только после `git apply` в изолированной временной копии,
   повторного `git diff --check`, проверок путей и синтаксиса.
6. Ответ без блока diff сохраняется как анализ: ничего не применяется.
7. Повторный импорт уже проверенного ответа отклоняется, кроме явного `--force`,
   и тогда предыдущие проверки сбрасываются.
8. Текст, похожий на shell-команды, никогда не исполняется; о нём только предупреждение.
9. Все текстовые артефакты — LF.
10. Состояние задачи — атомарная запись, переживает перезапуск процесса.

## Код для ревью

### hybrid/browser_bridge/sessions.py (хранилище)

```python
@dataclass
class BrowserTask:
    task_id: str; provider: str; description: str; profile: str; status: str
    task_mode: str = "browser"; url: str = ""
    prompt_path: str = ""; response_path: str | None = None
    review_path: str | None = None; engine_task_id: str | None = None
    skills: list[str] = field(default_factory=list)
    response_sha256: str | None = None; import_count: int = 0
    created_at: float = 0.0; updated_at: float = 0.0

class BrowserTaskStore:
    def import_response(self, task_id: str, text: str, force: bool = False) -> tuple[Path, str]:
        task = self.get(task_id)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if task.response_sha256 and not force:
            if digest == task.response_sha256:
                raise ResponseAlreadyImported("Identical response was already imported for this task")
            raise ResponseAlreadyImported(
                "A response was already imported and validated for this task; pass --force to replace it"
            )
        path = self.response_file(task_id)
        self._write_atomic(path, text.replace("\r\n", "\n"))
        task.response_path = str(path); task.response_sha256 = digest; task.import_count += 1
        self.save(task)
        return path, digest

    def _write_atomic(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
```

### hybrid/browser_bridge/response_parser.py (ядро)

```python
SECTION_RE = re.compile(r"^\s{0,3}#{1,6}\s*([A-Za-z][A-Za-z _/-]{1,40})\s*$", re.MULTILINE)
FENCE_RE = re.compile(r"```([A-Za-z0-9_+-]*)\n(.*?)```", re.DOTALL)
DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$", re.MULTILINE)
NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+?)\s*$", re.MULTILINE)
OLD_FILE_RE = re.compile(r"^--- (?:a/)?(.+?)\s*$", re.MULTILINE)
SHELL_HINT_RE = re.compile(r"(?im)^\s*(?:\$|>)\s*(?:git|php|npm|composer|mysql|cd|rm|mv|curl|wget|powershell)\b")
PATCH_LANGUAGES = {"diff", "patch"}
SENSITIVE_SEGMENTS = {".env", ".hybrid", "config/secrets", "tests/protected"}

class ResponseParser:
    def parse(self, task_id: str, text: str) -> ParsedResponse:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        parsed = ParsedResponse(task_id=task_id, response_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest())
        parsed.sections = self._split_sections(normalized)
        parsed.patch_blocks = [body.lstrip("\n") for language, body in self._fences(normalized)
                               if language in PATCH_LANGUAGES and body.strip()]
        if not parsed.patch_blocks:
            parsed.warnings.append("No diff block found; the answer is stored as an analysis, not a patch.")
            return parsed
        patch = parsed.patch_blocks[0].replace("\r\n", "\n")
        if not patch.endswith("\n"):
            patch += "\n"
        parsed.patch = patch
        if not patch.lstrip().startswith("diff --git"):
            parsed.warnings.append("The patch does not start with `diff --git`; it was not treated as an applicable diff.")
            parsed.patch = None
            return parsed
        parsed.is_patch = True
        parsed.files = self._patch_paths(patch)
        if SHELL_HINT_RE.search(normalized):
            parsed.warnings.append("The answer contains shell-looking lines. They are shown as text and never executed.")
        return parsed

    def validate_patch(self, parsed, settings, project_dir: Path) -> list[CheckResult]:
        results = []
        if not parsed.is_patch or not parsed.patch:
            return [CheckResult("Response Format", "FAIL", "No unified diff found in the response.")]
        blocked = []
        patterns = forbidden_patterns(settings)
        root = Path(project_dir).resolve()
        for rel in parsed.files:
            parts = Path(rel).parts
            if rel.startswith("/") or ".." in parts:
                blocked.append(f"{rel} (path escapes the project)"); continue
            if any(segment in rel for segment in SENSITIVE_SEGMENTS):
                blocked.append(f"{rel} (protected path)"); continue
            if is_forbidden(rel, patterns):
                blocked.append(f"{rel} (forbidden by configuration)"); continue
            try:
                (root / rel).resolve().relative_to(root)
            except ValueError:
                blocked.append(f"{rel} (resolves outside the project)")
        results.append(CheckResult("Patch Paths", "FAIL" if blocked else "PASS", "; ".join(blocked) or ", ".join(parsed.files)))
        return results
```

### hybrid/browser_bridge/controller.py (поток импорта, сокращённо)

```python
def import_response(self, task_id: str, text: str, force: bool = False) -> TaskRecord:
    browser_task = self._require(task_id)
    if not text or not text.strip():
        raise BrowserBridgeError("Imported response is empty")
    record = self._record(browser_task)
    guarded = {TaskStatus.READY_FOR_REVIEW.value, TaskStatus.APPLIED.value}
    if record.status in guarded and not force:
        raise ResponseAlreadyImported(f"{record.task_id} already has a validated result; re-import with --force to replace it")
    overwrite = bool(record.patch_sha256 or record.response_path)
    response_path, digest = self.store.import_response(task_id, text, force=force)
    parsed = self.parser.parse(record.task_id, text)
    record.response_path = str(response_path); record.response_sha256 = parsed.response_sha256
    record.import_count += 1; record.analysis = parsed.summary() or None
    if overwrite:
        parsed.warnings.append("A previously imported result was replaced because --force was used.")
        record.patch_sha256 = None; record.changed_files = []; record.checks = {}
    if not parsed.is_patch:
        record.status = TaskStatus.WAITING_FOR_USER.value
        self.controller.store.save(record)
        self.store.write_review(task_id, self._payload(record, parsed, "analysis_only", applied=False))
        return record
    path_checks = self.parser.validate_patch(parsed, self.settings, self.settings.root)
    hard = [c for c in path_checks if c.status == "FAIL"]
    if hard:
        record.status = TaskStatus.FAILED.value
        record.error = "; ".join(f"{c.name}: {c.detail}" for c in hard)
        self.controller.store.save(record)
        self.store.write_review(task_id, self._payload(record, parsed, "rejected", applied=False))
        return record
    record.base_commit = self._base_commit(); record.base_ref = record.base_commit
    self.controller._save_patch(record, parsed.patch or "")
    validation = self.controller._validate_patch_on_temp(record, parsed.patch or "")
    record.checks = {c.name: {"status": c.status, "detail": c.detail} for c in [*path_checks, *validation]}
    failed = self.controller._has_fail(validation)
    record.status = TaskStatus.FAILED.value if failed else TaskStatus.READY_FOR_REVIEW.value
    self.controller.store.save(record)
    self.store.write_review(task_id, self._payload(record, parsed, "patch_validated", applied=False))
    return record
```

### hybrid/visual/driver.py (запуск headless Chrome, сокращённо)

```python
BROWSER_NOISE_RE = re.compile(r"(sandbox\\policy|network_service_instance_impl|gpu_process|crashpad|CreateFile)", re.IGNORECASE)

def _run_file_logged(command: list[str], log_path: Path, timeout: int):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8", newline="\n") as handle:
        try:
            proc = subprocess.run(command, text=True, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout, check=False)
            output = log_path.read_text(encoding="utf-8", errors="replace")
            return subprocess.CompletedProcess(command, proc.returncode, stdout=output, stderr="")
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr=f"chrome timed out after {timeout}s")
```

## Формат ответа

```text
## VERDICT
одна строка: accept / accept with changes / reject

## ISSUES
- файл:строка — проблема, влияние, минимальное исправление
- (если проблем нет — напиши это прямо)

## PATCH
```diff
только реально необходимые точечные правки, либо: none
```

## LIMITATIONS
- что ты не мог оценить по приведённому коду
```

Приоритет ревью: утечка секретов, обход проверок путей, доверие к заголовкам
патча вместо содержимого, повторный импорт, обход shell-команд, зависания
процессов, ошибки на Windows (CRLF, пути, кодировки).
