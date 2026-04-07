from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import run
from typing import Optional


@dataclass
class GitWorktreePlan:
    repository: str
    branch_name: str
    worktree_path: str
    commands: list[str]


def current_branch(repo_path: str) -> Optional[str]:
    completed = run(
        ["git", "-C", repo_path, "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch = completed.stdout.strip()
    return branch or None


def has_remote(repo_path: str) -> bool:
    completed = run(
        ["git", "-C", repo_path, "remote"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(completed.stdout.strip())


def primary_remote(repo_path: str) -> Optional[str]:
    completed = run(
        ["git", "-C", repo_path, "remote"],
        capture_output=True,
        text=True,
        check=False,
    )
    remotes = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return remotes[0] if remotes else None


def branch_exists(repo_path: str, branch_name: str) -> bool:
    completed = run(
        ["git", "-C", repo_path, "show-ref", "--verify", f"refs/heads/{branch_name}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def build_worktree_plan(
    repo_path: str,
    branch_name: str,
    *,
    worktree_path: Optional[str] = None,
    base_branch: str = "main",
) -> GitWorktreePlan:
    path = Path(repo_path).resolve()
    target_worktree = Path(worktree_path).resolve() if worktree_path else path.parent / f"{path.name}-wt-{branch_name.replace('/', '-')}"
    commands: list[str] = []
    if has_remote(str(path)):
        commands.append(f"git -C {path} fetch --all --prune")

    if branch_exists(str(path), branch_name):
        commands.append(f"git -C {path} worktree add {target_worktree} {branch_name}")
    else:
        commands.append(f"git -C {path} worktree add {target_worktree} -b {branch_name} {base_branch}")
    return GitWorktreePlan(
        repository=str(path),
        branch_name=branch_name,
        worktree_path=str(target_worktree),
        commands=commands,
    )
