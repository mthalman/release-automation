import re
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=repo,
    ).decode("utf-8")


def safe_path(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", value):
        raise ValueError(f"Expected a relative repository path, got {value!r}.")
    if any(part in (".", "..") or part.lower() == ".git" for part in value.split("/")):
        raise ValueError(f"Unsafe repository path: {value!r}.")
    return value


def committed_file(repo: Path, commit: str, name: str) -> str | None:
    safe_path(name)
    entries = git(repo, "ls-tree", "-z", commit, "--", name).split("\0")
    entries = [entry for entry in entries if entry]
    if not entries:
        return None
    if len(entries) != 1 or not entries[0].startswith("100644 blob "):
        raise ValueError(f"{name}: expected a regular, non-executable committed file.")
    return git(repo, "show", f"{commit}:{name}")


def write_target(repo: Path, name: str) -> Path:
    safe_path(name)
    target = repo
    for part in name.split("/"):
        target = target / part
        if target.is_symlink():
            raise ValueError(f"Refusing to write through a symlink: {name}.")
    if not target.resolve().is_relative_to(repo.resolve()):
        raise ValueError(f"Path escapes repository: {name}.")
    return target
