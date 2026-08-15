"""
Deterministic git layer.

Per the design's first principle ("deterministic where possible, LLM only for
judgement"), everything here is computed by git, never guessed by a model:
cloning, branch discovery, and the diff. No LLM is involved.

Branches are addressed through their remote-tracking refs (``origin/<name>``).
A normal ``git clone`` creates a remote-tracking ref for every branch on the
remote, so all branches are diff-able immediately without extra checkouts.

The headline operation is the **three-dot diff** (``base...compare``): it shows
what ``compare`` introduced since it forked from ``base`` (i.e. changes since the
merge-base), which is exactly what a pull request shows — not the raw tip-to-tip
delta a two-dot diff would give.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .. import config


class GitError(Exception):
    """Raised when an underlying git command fails."""


def _run(args: list[str], cwd: Path | None = None, timeout: int = config.GIT_COMMAND_TIMEOUT) -> str:
    """Run ``git <args>`` and return stdout, raising GitError on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # git not installed
        raise GitError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {args[0]} timed out after {timeout}s") from exc

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise GitError(message or f"git {' '.join(args)} failed")
    return result.stdout


def _ref(branch: str) -> str:
    """Map a display branch name to its remote-tracking ref."""
    return f"origin/{branch}"


# --------------------------------------------------------------------------- #
# Clone
# --------------------------------------------------------------------------- #
def clone_repo(url: str, dest: Path) -> None:
    """
    Clone ``url`` into ``dest`` (replacing any existing directory).

    A plain full clone is used so every branch is available as a remote-tracking
    ref for later diffing.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["clone", url, str(dest)], timeout=config.GIT_CLONE_TIMEOUT)


# --------------------------------------------------------------------------- #
# Branch discovery
# --------------------------------------------------------------------------- #
def detect_default_branch(repo: Path) -> str | None:
    """Return the remote's default branch (what HEAD points at), if resolvable."""
    try:
        ref = _run(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=repo).strip()
        return ref.rsplit("/", 1)[-1] or None
    except GitError:
        # Fall back to common conventions, then to whatever exists.
        branches = list_branches(repo)
        for candidate in ("main", "master"):
            if candidate in branches:
                return candidate
        return branches[0] if branches else None


def list_branches(repo: Path) -> list[str]:
    """Return the sorted list of remote branch names (without the ``origin/`` prefix)."""
    out = _run(["branch", "-r"], cwd=repo)
    branches: set[str] = set()
    for raw in out.splitlines():
        line = raw.strip()
        if not line or "->" in line:  # skip the "origin/HEAD -> origin/main" line
            continue
        if line.startswith("origin/"):
            branches.add(line[len("origin/"):])
    return sorted(branches)


# --------------------------------------------------------------------------- #
# Diff (three-dot / merge-base)
# --------------------------------------------------------------------------- #
def _parse_changed_files(name_status: str, numstat: str) -> list[dict]:
    """Combine ``--name-status`` (statuses) with ``--numstat`` (line counts)."""
    # path -> (additions, deletions); "-" means binary → None
    counts: dict[str, tuple[int | None, int | None]] = {}
    for raw in numstat.splitlines():
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        adds, dels, path = parts[0], parts[1], parts[2]
        counts[path] = (
            None if adds == "-" else int(adds),
            None if dels == "-" else int(dels),
        )

    files: list[dict] = []
    for raw in name_status.splitlines():
        parts = raw.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        old_path = None
        if status[0] in ("R", "C") and len(parts) >= 3:
            old_path, path = parts[1], parts[2]
        else:
            path = parts[1]
        adds, dels = counts.get(path, (None, None))
        files.append(
            {
                "path": path,
                "status": status[0],
                "old_path": old_path,
                "additions": adds,
                "deletions": dels,
            }
        )
    return files


def diff_branches(repo: Path, base: str, compare: str) -> dict:
    """
    Compute the three-dot diff of ``compare`` against ``base``.

    Returns a dict with the merge-base commit, per-file change summary, aggregate
    stats, and the raw unified patch.
    """
    base_ref, compare_ref = _ref(base), _ref(compare)
    range_spec = f"{base_ref}...{compare_ref}"

    try:
        merge_base = _run(["merge-base", base_ref, compare_ref], cwd=repo).strip() or None
    except GitError:
        merge_base = None  # unrelated histories: git diff still works below

    name_status = _run(["diff", "--name-status", range_spec], cwd=repo)
    numstat = _run(["diff", "--numstat", range_spec], cwd=repo)
    patch = _run(["diff", range_spec], cwd=repo)

    changed_files = _parse_changed_files(name_status, numstat)
    stats = {
        "files_changed": len(changed_files),
        "additions": sum((f["additions"] or 0) for f in changed_files),
        "deletions": sum((f["deletions"] or 0) for f in changed_files),
    }

    return {
        "base": base,
        "compare": compare,
        "merge_base": merge_base,
        "stats": stats,
        "changed_files": changed_files,
        "diff": patch,
    }

def file_content_at(repo: Path, branch: str, path: str) -> str | None:
    """Text of `path` as it exists on the compare branch, or None if absent."""
    try:
        return _run(["show", f"{_ref(branch)}:{path}"], cwd=repo)
    except GitError:
        return None

# --------------------------------------------------------------------------- #
# File tree (rung 1 of the map climb — Design §7.2)
# --------------------------------------------------------------------------- #
def list_files(repo: Path) -> list[str]:
    """Every tracked file, repo-relative — the deterministic file tree.

    ``git ls-files`` lists exactly what git tracks on the checked-out branch
    (the clone's default branch, which is the side the map is built from).
    Ignored files never appear, so no extra filtering is needed.
    """
    out = _run(["ls-files"], cwd=repo)
    return [line for line in out.splitlines() if line]
