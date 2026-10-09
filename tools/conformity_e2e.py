"""Master Conformity E2E: the real run -> review -> report -> apply route.

This is not a unit test. It builds a throwaway Git repository on disk, drives the
*installed* `hybrid` CLI against it as a subprocess, and records what actually
happened. Every assertion is about observable state (files, git status, exit
codes, artifact hashes), never about internal Python objects.

Usage:
    .venv\\Scripts\\python.exe tools\\conformity_e2e.py [--keep]

Exit code 0 means every scenario passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

results: list[dict] = []


def record(scenario: str, status: str, evidence: str) -> None:
    results.append({"scenario": scenario, "status": status, "evidence": evidence})
    print(f"[{status:8}] {scenario}")
    for line in evidence.splitlines():
        print(f"           {line}")


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)


def hybrid(args: list[str], cwd: Path, data_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HYBRID_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [str(PYTHON), "-m", "hybrid.cli", "--project", str(cwd), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def make_repo(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git(["init", "-q"], root)
    git(["config", "user.email", "e2e@example.invalid"], root)
    git(["config", "user.name", "E2E"], root)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "baseline"], root)


BASE_FILES = {
    "app.js": 'export const value = "BROKEN";\n',
    "index.php": "<?php echo 'ok'; ?>\n",
}


def scenario_happy_path(tmp: Path) -> None:
    """1.1 -- the full route: run -> status -> report -> review -> apply."""
    name = "1.1 happy path run->status->report->review->apply (mock, safe)"
    repo = tmp / "happy"
    data = repo / ".hybrid"
    make_repo(repo, BASE_FILES)
    before = (repo / "app.js").read_text(encoding="utf-8")

    run = hybrid(["run", "fix small label", "--mode", "safe", "--provider", "mock"], repo, data)
    task_id = ""
    for line in run.stdout.splitlines():
        if line.startswith("TASK-"):
            task_id = line.strip()
    if run.returncode != 0 or not task_id:
        return record(name, "FAIL", f"run failed rc={run.returncode}\nstdout={run.stdout[-800:]}\nstderr={run.stderr[-800:]}")

    status = hybrid(["status", task_id], repo, data)
    report = hybrid(["report", task_id], repo, data)
    review = hybrid(["review", task_id], repo, data)

    # The project must be untouched before apply.
    after_run = (repo / "app.js").read_text(encoding="utf-8")
    porcelain = git(["status", "--porcelain"], repo).stdout.strip()

    evidence = [
        f"task={task_id}",
        f"run rc={run.returncode} status={[l for l in status.stdout.splitlines() if l.startswith('Status')]}",
        f"review rc={review.returncode}",
        f"project unchanged before apply: {after_run == before}",
        f"git status --porcelain empty: {porcelain == ''!r} -> {porcelain!r}",
    ]

    apply_no_yes = hybrid(["apply", task_id], repo, data)
    after_blocked = (repo / "app.js").read_text(encoding="utf-8")
    evidence.append(f"apply without --yes rc={apply_no_yes.returncode} (non-zero required: {apply_no_yes.returncode != 0})")
    evidence.append(f"project still unchanged after refused apply: {after_blocked == before}")

    apply_yes = hybrid(["apply", task_id, "--yes"], repo, data)
    final = (repo / "app.js").read_text(encoding="utf-8")
    evidence.append(f"apply --yes rc={apply_yes.returncode} -> content={final.strip()!r}")

    repeat = hybrid(["apply", task_id, "--yes"], repo, data)
    evidence.append(f"repeat apply rc={repeat.returncode} (non-zero required: {repeat.returncode != 0})")
    evidence.append(f"report mentions review: {'Review Required' in report.stdout or 'review' in report.stdout.lower()}")

    ok = (
        run.returncode == 0
        and status.returncode == 0
        and report.returncode == 0
        and review.returncode == 0
        and after_run == before
        and porcelain == ""
        and apply_no_yes.returncode != 0
        and after_blocked == before
        and apply_yes.returncode == 0
        and "FIXED" in final
        and repeat.returncode != 0
    )
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_fast_mode_isolation(tmp: Path) -> None:
    """1.4 -- FAST MODE must not write to the real project before apply."""
    name = "1.4 fast mode never writes the project before apply"
    repo = tmp / "fast"
    data = repo / ".hybrid"
    make_repo(repo, BASE_FILES)
    before = (repo / "app.js").read_text(encoding="utf-8")

    run = hybrid(["run", "fix small label", "--mode", "fast", "--provider", "mock"], repo, data)
    task_id = next((l.strip() for l in run.stdout.splitlines() if l.startswith("TASK-")), "")
    after = (repo / "app.js").read_text(encoding="utf-8")
    porcelain = git(["status", "--porcelain"], repo).stdout.strip()
    evidence = [
        f"run rc={run.returncode} task={task_id}",
        f"project file unchanged: {after == before}",
        f"git status --porcelain: {porcelain!r}",
        f"bare patch artifact exists: {(data / 'tasks' / task_id / 'proposed.patch').exists() if task_id else 'n/a'}",
    ]
    ok = run.returncode == 0 and after == before and porcelain == ""
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_tampered_patch(tmp: Path) -> None:
    """1.2 C -- a substituted patch must not be applied."""
    name = "1.2C tampered patch artifact is refused at apply"
    repo = tmp / "tamper"
    data = repo / ".hybrid"
    make_repo(repo, BASE_FILES)

    run = hybrid(["run", "fix small label", "--mode", "safe", "--provider", "mock"], repo, data)
    task_id = next((l.strip() for l in run.stdout.splitlines() if l.startswith("TASK-")), "")
    if not task_id:
        return record(name, "FAIL", f"no task id\n{run.stdout[-500:]}")

    patch = data / "tasks" / task_id / "proposed.patch"
    original = patch.read_text(encoding="utf-8")
    before = (repo / "app.js").read_text(encoding="utf-8")
    # Substitute a different, still-valid-looking patch body.
    patch.write_text(original.replace("FIXED", "TAMPERED"), encoding="utf-8")

    apply = hybrid(["apply", task_id, "--yes"], repo, data)
    after = (repo / "app.js").read_text(encoding="utf-8")
    evidence = [
        f"artifact sha256 before={hashlib.sha256(original.encode()).hexdigest()[:16]}",
        f"artifact sha256 after ={hashlib.sha256(patch.read_text(encoding='utf-8').encode()).hexdigest()[:16]}",
        f"apply rc={apply.returncode} (non-zero required: {apply.returncode != 0})",
        f"error mentions patch: {'patch' in (apply.stdout + apply.stderr).lower()}",
        f"project unchanged: {after == before}",
    ]
    ok = apply.returncode != 0 and after == before and "patch" in (apply.stdout + apply.stderr).lower()
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_user_change_conflict(tmp: Path) -> None:
    """1.2 C -- a user edit after review invalidates the approval."""
    name = "1.2C user edit after review blocks apply"
    repo = tmp / "conflict"
    data = repo / ".hybrid"
    make_repo(repo, BASE_FILES)

    run = hybrid(["run", "fix small label", "--mode", "safe", "--provider", "mock"], repo, data)
    task_id = next((l.strip() for l in run.stdout.splitlines() if l.startswith("TASK-")), "")
    if not task_id:
        return record(name, "FAIL", f"no task id\n{run.stdout[-500:]}")

    (repo / "app.js").write_text('export const value = "USER EDIT";\n', encoding="utf-8")
    apply = hybrid(["apply", task_id, "--yes"], repo, data)
    after = (repo / "app.js").read_text(encoding="utf-8")
    combined = apply.stdout + apply.stderr
    evidence = [
        f"apply rc={apply.returncode} (non-zero required: {apply.returncode != 0})",
        f"refusal reason present: {'local changes' in combined.lower() or 'head changed' in combined.lower()}",
        f"user edit survived: {'USER EDIT' in after}",
    ]
    ok = apply.returncode != 0 and "USER EDIT" in after
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_hybrid_internal_state(tmp: Path) -> None:
    """1.2 A -- a patch must not silently change engine state under .hybrid/."""
    name = "1.2A .hybrid internal state is never part of a task diff"
    repo = tmp / "state"
    data = repo / ".hybrid"
    make_repo(repo, BASE_FILES)

    run = hybrid(["run", "fix small label", "--mode", "safe", "--provider", "mock"], repo, data)
    task_id = next((l.strip() for l in run.stdout.splitlines() if l.startswith("TASK-")), "")
    if not task_id:
        return record(name, "FAIL", f"no task id\n{run.stdout[-500:]}")
    diff = hybrid(["review", task_id], repo, data)
    body = diff.stdout
    evidence = [
        f"diff mentions .hybrid/: {'.hybrid/' in body}",
        f"diff files: {[l for l in body.splitlines() if l.startswith('+++')]}",
    ]
    ok = ".hybrid/" not in body and "app.js" in body
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_forbidden_path(tmp: Path) -> None:
    """1.2 -- a forbidden path (.env) is refused by path validation."""
    name = "1.2 forbidden path .env is refused"
    repo = tmp / "forbidden"
    data = repo / ".hybrid"
    make_repo(repo, {**BASE_FILES, ".env": "SECRET=1\n"})

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["HYBRID_DATA_DIR"] = str(data)
    code = (
        "from pathlib import Path;"
        "from hybrid.config import load_settings;"
        "from hybrid.quality.checks import validate_paths;"
        "s=load_settings(Path(r'%s'));"
        "r=validate_paths(Path(r'%s'), ['.env'], s.raw['architecture']);"
        "print([(x.name,x.status) for x in r])" % (repo, repo)
    )
    proc = subprocess.run([str(PYTHON), "-c", code], cwd=REPO_ROOT, text=True, capture_output=True, env=env, check=False)
    evidence = [f"validate_paths(.env) -> {proc.stdout.strip()}", f"rc={proc.returncode}"]
    ok = proc.returncode == 0 and "FAIL" in proc.stdout and "forbidden path" in proc.stdout
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_max_files(tmp: Path) -> None:
    """1.2 -- the architecture file limit is enforced."""
    name = "1.2 max_files_changed is enforced"
    repo = tmp / "maxfiles"
    data = repo / ".hybrid"
    make_repo(repo, BASE_FILES)
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), HYBRID_DATA_DIR=str(data))
    code = (
        "from pathlib import Path;"
        "from hybrid.config import load_settings;"
        "from hybrid.quality.checks import validate_paths;"
        "s=load_settings(Path(r'%s'));"
        "r=validate_paths(Path(r'%s'), [f'f{i}.js' for i in range(9)], s.raw['architecture']);"
        "print([(x.name,x.status) for x in r])" % (repo, repo)
    )
    proc = subprocess.run([str(PYTHON), "-c", code], cwd=REPO_ROOT, text=True, capture_output=True, env=env, check=False)
    evidence = [f"validate_paths(9 files) -> {proc.stdout.strip()}"]
    ok = "FAIL" in proc.stdout and "max files" in proc.stdout
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def scenario_ignored_dirs(tmp: Path) -> None:
    """1.2 B -- an unchanged dependency dir must not be a false FAIL, but a
    real change inside an ignored dir must be visible."""
    name = "1.2B ignored dirs: unchanged node_modules does not FAIL"
    repo = tmp / "ignored"
    data = repo / ".hybrid"
    make_repo(repo, {**BASE_FILES, ".gitignore": "node_modules/\ndist/\n"})
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("module.exports=1;\n", encoding="utf-8")

    run = hybrid(["run", "fix small label", "--mode", "safe", "--provider", "mock"], repo, data)
    task_id = next((l.strip() for l in run.stdout.splitlines() if l.startswith("TASK-")), "")
    status = hybrid(["status", task_id], repo, data) if task_id else None
    combined = (status.stdout + status.stderr) if status else run.stdout
    evidence = [
        f"run rc={run.returncode} task={task_id}",
        f"status rc={status.returncode if status else 'n/a'}",
        f"status mentions node_modules: {'node_modules' in combined}",
    ]
    ok = run.returncode == 0 and task_id and "FAIL" not in combined.upper().replace("READY_FOR_REVIEW", "")
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the temporary repositories")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="hybrid-conformity-"))
    print(f"workspace: {tmp}\n")
    try:
        scenario_happy_path(tmp)
        scenario_fast_mode_isolation(tmp)
        scenario_tampered_patch(tmp)
        scenario_user_change_conflict(tmp)
        scenario_hybrid_internal_state(tmp)
        scenario_forbidden_path(tmp)
        scenario_max_files(tmp)
        scenario_ignored_dirs(tmp)
    finally:
        if args.keep:
            print(f"\nkept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] != "PASS")
    print(f"\n=== {passed} PASS / {failed} FAIL / {len(results)} total ===")
    out = REPO_ROOT / "docs" / "conformity_e2e_result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"evidence written: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
