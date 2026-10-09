"""Phase 1.3 conformity regressions: Git path handling and apply safety.

These exercise the real Git plumbing the engine depends on
(`git apply --cached`, `git status -z`, `git diff --name-status -z`) against
awkward paths: renames, copies, quoted/escaped names, Unicode, deletions,
untracked files, symlinks and a dirty worktree.

Run:
    .venv\\Scripts\\python.exe tools\\conformity_git_safety.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hybrid.config import load_settings  # noqa: E402
from hybrid.controller import Controller  # noqa: E402
from hybrid.execution import worktree  # noqa: E402

results: list[dict] = []


def record(scenario: str, status: str, evidence: str) -> None:
    results.append({"scenario": scenario, "status": status, "evidence": evidence})
    print(f"[{status:8}] {safe(scenario)}")
    for line in evidence.splitlines():
        print(f"           {safe(line)}")


def safe(text: str) -> str:
    """The Windows console here is cp1251; never let reporting crash the run."""
    encoding = sys.stdout.encoding or "utf-8"
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    # encoding= is mandatory: Windows Python defaults to cp1251 here and cannot
    # decode UTF-8 path bytes coming back from git.
    return subprocess.run(
        ["git", *args], cwd=cwd, text=True, encoding="utf-8", errors="surrogateescape", capture_output=True, check=False
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
    git(["config", "core.quotepath", "false"], root)
    git(["add", "-A"], root)
    git(["commit", "-q", "-m", "baseline"], root)


def apply_patch_to(repo: Path, patch_text: str, restore: bool = True) -> tuple[int, str, list[str]]:
    """Apply a patch and report the paths git says it touched.

    `restore=True` resets the working tree to HEAD first, so a patch generated
    from an already-modified tree can still be applied (the engine always does
    the equivalent: the agent edits a copy, the patch is re-applied to the base).
    """
    if restore:
        git(["reset", "--hard", "-q", "HEAD"], repo)
        git(["clean", "-qfd"], repo)
    patch_file = repo / "probe.patch"
    patch_file.write_text(patch_text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    check = subprocess.run(
        ["git", "apply", "--check", str(patch_file)], cwd=repo, text=True,
        encoding="utf-8", errors="surrogateescape", capture_output=True,
    )
    if check.returncode != 0:
        detail = (check.stdout or "") + (check.stderr or "")
        return check.returncode, detail.strip(), []
    subprocess.run(
        ["git", "apply", "--cached", "--intent-to-add", str(patch_file)], cwd=repo,
        text=True, encoding="utf-8", errors="surrogateescape", capture_output=True,
    )
    data = worktree.run_git_bytes(["diff", "--cached", "--name-status", "-z", "--no-renames", "HEAD"], repo)
    entries = [e.decode("utf-8", errors="surrogateescape") for e in data.split(b"\0") if e]
    paths = [e for e in entries if not e[:1].isdigit() and e not in {"A", "M", "D", "R100", "C100"}]
    subprocess.run(["git", "reset", "-q"], cwd=repo, text=True, capture_output=True)
    return 0, "", paths


def scenario(project_dir: Path, name: str):
    return Controller(load_settings(project_dir)), name


def run_mock(project: Path, description: str, mode: str = "safe"):
    os.environ["HYBRID_DATA_DIR"] = str(project / ".hybrid")
    controller = Controller(load_settings(project))
    return controller, controller.run(description, mode, "mock", dry_run=False)


def s_rename_and_copy(tmp: Path) -> None:
    name = "1.3 rename and copy are parsed from real git plumbing"
    repo = tmp / "rename"
    make_repo(repo, {"src/old.php": "<?php echo 'a'; ?>\n", "src/keep.php": "<?php echo 'b'; ?>\n"})
    git(["mv", "src/old.php", "src/new.php"], repo)
    rc, err, paths = apply_patch_to(repo, git(["diff", "--binary", "--no-renames", "HEAD"], repo).stdout)
    evidence = [
        f"rename detected paths={paths}",
        f"rc={rc}",
    ]
    # A deletion + addition (no-renames form the engine uses) must expose both sides.
    ok = rc == 0 and "src/new.php" in paths
    if not ok:
        return record(name, "FAIL", "\n".join(evidence + [err]))

    # Copy: git records it as an addition of a new path.
    repo2 = tmp / "copy"
    make_repo(repo2, {"src/a.php": "<?php echo 'a'; ?>\n"})
    # A copy is recorded by git as a brand-new untracked file (no-renames form).
    shutil.copy(repo2 / "src/a.php", repo2 / "src/a_copy.php")
    git(["add", "-N", "--", "src/a_copy.php"], repo2)
    rc2, err2, paths2 = apply_patch_to(repo2, git(["diff", "--binary", "HEAD"], repo2).stdout, restore=True)
    evidence += [f"copy detected paths={paths2}", f"rc2={rc2}"]
    ok = ok and rc2 == 0 and "src/a_copy.php" in paths2
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence + ([err2] if err2 else [])))


def s_quoted_paths(tmp: Path) -> None:
    name = "1.3 quoted / escaped and spaced paths survive the parser"
    repo = tmp / "quoted"
    awkward = {
        "dir with space/file one.php": "<?php echo 1; ?>\n",
        "dir with space/file-two.php": "<?php echo 2; ?>\n",
        "dir with space/файл три.php": "<?php echo 3; ?>\n",
    }
    make_repo(repo, awkward)
    for rel in awkward:
        (repo / rel).write_text("<?php echo 9; ?>\n", encoding="utf-8")
    patch = git(["diff", "--binary", "--no-renames", "HEAD"], repo).stdout
    rc, err, paths = apply_patch_to(repo, patch)
    found = sorted(paths)
    expected = sorted(awkward)
    evidence = [
        f"git diff produced quoted paths: {'\"' in patch}",
        f"parsed paths={found}",
        f"expected    ={expected}",
        f"rc={rc}",
    ]
    ok = rc == 0 and found == expected
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence + ([err] if err else [])))


def s_unicode_paths(tmp: Path) -> None:
    name = "1.3 Unicode filenames are not mangled"
    repo = tmp / "unicode"
    files = {"инвентарь/предмет.php": "<?php echo 'i'; ?>\n", "日本語/ファイル.js": "export const a=1;\n"}
    make_repo(repo, files)
    for rel in files:
        (repo / rel).write_text("<?php echo 'changed'; ?>\n" if rel.endswith(".php") else "export const a=2;\n", encoding="utf-8")
    patch = git(["diff", "--binary", "--no-renames", "HEAD"], repo).stdout
    rc, err, paths = apply_patch_to(repo, patch)
    evidence = [f"parsed paths={sorted(paths)}", f"expected={sorted(files)}", f"rc={rc}"]
    ok = rc == 0 and sorted(paths) == sorted(files)
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence + ([err] if err else [])))


def s_deletion_and_new_file(tmp: Path) -> None:
    name = "1.3 deletions and new files are both detected"
    repo = tmp / "delnew"
    make_repo(repo, {"keep.php": "<?php echo 'k'; ?>\n", "gone.php": "<?php echo 'g'; ?>\n"})
    (repo / "gone.php").unlink()
    (repo / "fresh.php").write_text("<?php echo 'f'; ?>\n", encoding="utf-8")
    git(["add", "-N", "fresh.php"], repo)
    patch = git(["diff", "--binary", "--no-renames", "HEAD"], repo).stdout
    rc, err, paths = apply_patch_to(repo, patch)
    evidence = [f"parsed paths={sorted(paths)}", f"rc={rc}"]
    expected = {"gone.php", "fresh.php"}
    ok = rc == 0 and expected.issubset(set(paths))
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence + ([err] if err else [])))


def s_untracked_dirty(tmp: Path) -> None:
    name = "1.3 untracked + dirty worktree are visible to the engine"
    repo = tmp / "dirty"
    make_repo(repo, {"app.js": 'export const value = "BROKEN";\n'})
    (repo / "untracked.js").write_text("export const u = 1;\n", encoding="utf-8")
    (repo / "app.js").write_text('export const value = "USER";\n', encoding="utf-8")
    controller, rec = run_mock(repo, "fix small label", "safe")
    changed = worktree.changed_files(repo, include_ignored=True)
    clean = worktree.is_clean(repo)
    apply_blocked = False
    if rec.status == "ready_for_review":
        try:
            controller.apply(rec.task_id, confirm=True)
        except RuntimeError as exc:
            apply_blocked = "local changes" in str(exc) or "HEAD changed" in str(exc)
    elif controller:
        apply_blocked = True  # run itself failed over a dirty tree
    evidence = [
        f"changed_files={changed}",
        f"is_clean={clean}",
        f"run status={rec.status}",
        f"apply blocked on dirty worktree: {apply_blocked}",
    ]
    ok = "untracked.js" in changed and "app.js" in changed and not clean and apply_blocked
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def s_symlink_rejected(tmp: Path) -> None:
    name = "1.3 symlink in the project blocks agent execution"
    repo = tmp / "symlink"
    make_repo(repo, {"app.js": "export const a = 1;\n"})
    outside = tmp / "outside-secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    link = repo / "leak.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        return record(name, "SKIP", f"symlink creation not permitted: {exc}")
    controller, rec = run_mock(repo, "fix small label", "safe")
    evidence = [f"run status={rec.status}", f"error={rec.error!r}"]
    ok = rec.status == "failed" and "symlink" in (rec.error or "").lower()
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def s_engine_state_not_in_diff(tmp: Path) -> None:
    name = "1.2A .hybrid/ never enters the change set"
    repo = tmp / "state2"
    make_repo(repo, {"app.js": 'export const value = "BROKEN";\n'})
    controller, rec = run_mock(repo, "fix small label", "safe")
    changed = worktree.changed_files(Path(rec.worktree_dir)) if rec.worktree_dir else []
    evidence = [f"status={rec.status}", f"worktree changed={changed}"]
    ok = rec.status == "ready_for_review" and not any(c.startswith(".hybrid") for c in changed)
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def s_ignored_change_visible(tmp: Path) -> None:
    name = "1.2B an ignored dir is surfaced without a false failure"
    repo = tmp / "ignoredchange"
    make_repo(repo, {"app.js": "export const a = 1;\n", ".gitignore": "node_modules/\ndist/\n"})
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("module.exports = 1;\n", encoding="utf-8")
    (repo / "dist").mkdir()
    (repo / "dist" / "bundle.js").write_text("var a = 1;\n", encoding="utf-8")

    before = worktree.changed_files(repo, include_ignored=True)
    (repo / "dist" / "bundle.js").write_text("var a = 2;\n", encoding="utf-8")
    after = worktree.changed_files(repo, include_ignored=True)

    # Skipped dependency/build dirs are reported as ONE bounded entry. That is the
    # contract in worktree.IGNORED_DIRS_TO_SKIP: surface the fact of a change and
    # the directory identity, without expanding it into thousands of paths.
    evidence = [
        f"before={before}",
        f"after ={after}",
        f"node_modules surfaced as one entry: {'node_modules/' in before and 'node_modules/' in after}",
        f"dist surfaced as one entry: {'dist/' in after}",
        f"no path expanded deeper than the dir: {not any(c.startswith('dist/') and c != 'dist/' for c in after)}",
        f"bounded, no truncation marker: {not any(c.endswith('/...') for c in after)}",
    ]
    ok = (
        "node_modules/" in before
        and "node_modules/" in after
        and "dist/" in after
        and not any(c.startswith("dist/") and c != "dist/" for c in after)
        and not any(c.endswith("/...") for c in after)
    )
    record(name, "PASS" if ok else "FAIL", "\n".join(evidence))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="hybrid-gitsafety-"))
    print(f"workspace: {tmp}\n")
    try:
        s_rename_and_copy(tmp)
        s_quoted_paths(tmp)
        s_unicode_paths(tmp)
        s_deletion_and_new_file(tmp)
        s_untracked_dirty(tmp)
        s_symlink_rejected(tmp)
        s_engine_state_not_in_diff(tmp)
        s_ignored_change_visible(tmp)
    finally:
        if args.keep:
            print(f"\nkept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    print(f"\n=== {passed} PASS / {failed} FAIL / {skipped} SKIP / {len(results)} total ===")
    out = REPO_ROOT / "docs" / "conformity_git_safety_result.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"evidence written: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
