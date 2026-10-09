from __future__ import annotations

from pathlib import Path
import subprocess

MAX_IGNORED_FILES = 200
IGNORED_DIRS_TO_SKIP = {"node_modules", "vendor", ".venv", "venv", "dist", "build", ".cache"}


class GitError(RuntimeError):
    pass


def run_git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.rstrip("\n")


def run_git_bytes(args: list[str], cwd: Path) -> bytes:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode("utf-8", errors="replace").strip()
        raise GitError(detail)
    return proc.stdout


def is_git_repo(path: Path) -> bool:
    proc = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=path, text=True, capture_output=True)
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        return False
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, text=True, capture_output=True)
    return top.returncode == 0 and Path(top.stdout.strip()).resolve() == path.resolve()


def ensure_repo(path: Path) -> None:
    if not is_git_repo(path):
        raise GitError("Project is not a Git repository. Run git init/commit yourself before using Hybrid Engine.")


def base_commit(path: Path) -> str:
    return run_git(["rev-parse", "HEAD"], path)


def fetch_from(source_repo: Path, clone_dir: Path, ref: str) -> None:
    """Copy the objects a patch refers to into a temporary clone.

    A patch carries blob ids of the real project HEAD. A fresh clone knows
    nothing about them, so `git apply` rejects an otherwise valid patch. Pull
    the exact commit into the clone (local git protocol, no working tree) so the
    artifact the user pasted is the artifact that gets validated.
    """
    remote = "__hybrid_source__"
    url = Path(source_repo).resolve().as_uri()
    subprocess.run(["git", "remote", "remove", remote], cwd=clone_dir, text=True, capture_output=True, check=False)
    added = subprocess.run(["git", "remote", "add", remote, url], cwd=clone_dir, text=True, capture_output=True, check=False)
    if added.returncode != 0:
        raise GitError(added.stderr.strip() or "Could not register the source repository as a remote")
    fetched = subprocess.run(
        ["git", "fetch", "--no-tags", "--quiet", remote, ref],
        cwd=clone_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if fetched.returncode != 0:
        raise GitError(fetched.stderr.strip() or "Could not fetch the base commit into the temporary copy")
    reset = subprocess.run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=clone_dir, text=True, capture_output=True, check=False)
    if reset.returncode != 0:
        raise GitError(reset.stderr.strip() or "Could not reset the temporary copy to the fetched commit")


def create_worktree(project_dir: Path, task_id: str, data_dir: Path) -> tuple[Path, str]:
    branch = f"hybrid/{task_id.lower()}"
    wt_root = data_dir / "worktrees"
    wt_root.mkdir(parents=True, exist_ok=True)
    wt_dir = wt_root / task_id
    run_git(["worktree", "add", "-b", branch, str(wt_dir)], project_dir)
    return wt_dir, branch


def changed_files(path: Path, include_ignored: bool = True) -> list[str]:
    args = ["status", "--porcelain=v1", "-z", "--untracked-files=all"]
    if include_ignored:
        args.append("--ignored=matching")
    out = run_git(args, path)
    entries = [item for item in out.split("\0") if item]
    files: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        status = entry[:2]
        rel = entry[3:]
        if rel.startswith(".hybrid/") or rel == ".hybrid":
            index += 1
            continue
        if status == "!!":
            full = path / rel
            if full.is_file() or full.is_symlink():
                files.append(rel)
            elif full.is_dir():
                files.extend(_ignored_dir_files(path, full))
            index += 1
            continue
        if "R" in status or "C" in status:
            files.append(rel)
            files.append(entries[index + 1])
            index += 2
            continue
        files.append(rel)
        index += 1
    return sorted(set(files))


def _ignored_dir_files(root: Path, directory: Path) -> list[str]:
    if directory.name in IGNORED_DIRS_TO_SKIP:
        return [directory.relative_to(root).as_posix() + "/"]
    found: list[str] = []
    for child in sorted(directory.rglob("*")):
        if any(part in IGNORED_DIRS_TO_SKIP for part in child.relative_to(directory).parts):
            continue
        if child.is_file() or child.is_symlink():
            found.append(child.relative_to(root).as_posix())
            if len(found) >= MAX_IGNORED_FILES:
                found.append(directory.relative_to(root).as_posix() + "/...")
                break
    return found


def prepare_untracked_for_diff(path: Path) -> None:
    for rel in changed_files(path):
        full = path / rel
        if full.exists() and not full.is_dir():
            proc = subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel], cwd=path, text=True, capture_output=True)
            if proc.returncode != 0:
                subprocess.run(["git", "add", "-N", "-f", "--", rel], cwd=path, text=True, capture_output=True, check=False)


def affected_paths_from_patch(path: Path, patch_file: Path) -> list[str]:
    try:
        # --cached only: combining it with --index re-checks the patched blob
        # against the working tree and fails on line-ending normalization.
        run_git(["apply", "--cached", "--intent-to-add", str(patch_file)], path)
        data = run_git_bytes(["diff", "--cached", "--name-status", "-z", "--no-renames", "HEAD"], path)
        entries = [item.decode("utf-8", errors="surrogateescape") for item in data.split(b"\0") if item]
        files: list[str] = []
        index = 0
        while index < len(entries):
            status = entries[index]
            index += 1
            path_count = 2 if status[:1] in {"R", "C"} else 1
            for _ in range(path_count):
                if index >= len(entries):
                    raise GitError("Unexpected git name-status output while parsing patch paths")
                rel = entries[index]
                index += 1
                if rel and rel != "/dev/null" and not rel.startswith(".hybrid/"):
                    files.append(rel)
        return sorted(set(files))
    finally:
        subprocess.run(["git", "reset", "-q"], cwd=path, text=True, capture_output=True, check=False)


def prepare_paths_for_diff(path: Path, paths: list[str]) -> None:
    for rel in paths:
        full = path / rel
        if full.exists() and not full.is_dir():
            subprocess.run(["git", "add", "-N", "-f", "--", rel], cwd=path, text=True, capture_output=True, check=False)


def diff(path: Path) -> str:
    prepare_untracked_for_diff(path)
    proc = subprocess.run(["git", "diff", "--no-ext-diff", "--no-textconv", "--binary", "--no-renames", "HEAD"], cwd=path, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise GitError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout


def diff_stat(path: Path) -> str:
    return run_git(["diff", "--stat", "HEAD"], path)


def is_clean(path: Path) -> bool:
    return not changed_files(path)

