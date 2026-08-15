"""Ruff runner - readability (naming, magic numbers, control flow) and part of
maintainability (pyflakes/bugbear warnings, pyupgrade idioms), plus formatting
drift via `ruff format` (Design section 5, Python adapter).

Ruff is the one genuine compiled binary in the Python adapter, so unlike lizard and
radon (used through their Python APIs) it is invoked as a subprocess. The binary is
located in config.BIN_DIR (installed by setup.py) with a fallback to any `ruff` on
PATH. Runs are hermetic (`--isolated --no-cache`) so results depend only on our flags,
never on config files that happen to sit in the analysed tree.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .. import config
from ..agents.types import ToolFinding

# Exactly the rule families the design assigns to Ruff. Restricting the selection is
# what makes prefix-based axis routing safe (see routing.py).
SELECT = "N,RET,SIM,F,B,UP,PLR2004"
SUPPORTED_SUFFIXES = {".py"}


def _ruff_binary() -> str:
    """Locate the ruff executable: project bin/ first, then PATH."""
    candidate = config.BIN_DIR / ("ruff.exe" if os.name == "nt" else "ruff")
    if candidate.exists():
        return str(candidate)
    found = shutil.which("ruff")
    if found:
        return found
    raise RuntimeError(
        "ruff binary not found. Run `python setup.py` to download it into "
        f"{config.BIN_DIR}, or install it with `pip install ruff`."
    )


def run(files: list[Path], rel_to: Path) -> list[ToolFinding]:
    """Analyse the .py files in `files`; emit findings with paths relative to rel_to."""
    py = [p for p in files if p.suffix in SUPPORTED_SUFFIXES]
    if not py:
        return []
    ruff = _ruff_binary()
    # Ruff reports absolute filenames even for relative args, so map them back ourselves.
    relmap = {str(p.resolve()): str(p.relative_to(rel_to)) for p in py}
    args = [str(p.resolve()) for p in py]
    findings: list[ToolFinding] = []
    findings += _run_check(ruff, args, relmap)
    findings += _run_format(ruff, args, relmap)
    return findings


def _relativize(filename: str, relmap: dict[str, str]) -> str:
    return relmap.get(str(Path(filename).resolve()), filename)


def _run_check(ruff: str, args: list[str], relmap: dict[str, str]) -> list[ToolFinding]:
    proc = subprocess.run(
        [
            ruff,
            "check",
            "--isolated",
            "--no-cache",
            "--select",
            SELECT,
            "--output-format",
            "json",
            *args,
        ],
        capture_output=True,
        text=True,
    )
    out = proc.stdout.strip()
    if not out:
        return []
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return []
    findings: list[ToolFinding] = []
    for r in rows:
        loc = r.get("location") or {}
        end = r.get("end_location") or {}
        findings.append(
            ToolFinding(
                tool="ruff",
                signal=r.get("code") or "?",
                path=_relativize(r.get("filename") or "?", relmap),
                line=loc.get("row"),
                end_line=end.get("row"),
                message=r.get("message") or "",
            )
        )
    return findings


def _run_format(
    ruff: str, args: list[str], relmap: dict[str, str]
) -> list[ToolFinding]:
    proc = subprocess.run(
        [ruff, "format", "--isolated", "--no-cache", "--check", "--diff", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:  # everything already formatted
        return []
    return _parse_format_diff(proc.stdout, relmap)


def _parse_format_diff(stdout: str, relmap: dict[str, str]) -> list[ToolFinding]:
    """Turn a `ruff format --diff` unified diff into one finding per file, with the
    number of changed lines as the metric (a proxy for formatting drift)."""
    findings: list[ToolFinding] = []
    current: str | None = None
    changed = 0

    def flush() -> None:
        nonlocal current, changed
        if current is not None and changed > 0:
            findings.append(
                ToolFinding(
                    tool="ruff-format",
                    signal="format-diff",
                    path=_relativize(current, relmap),
                    line=None,
                    message=f"{changed} line(s) differ from `ruff format` output.",
                    metric=changed,
                )
            )
        current, changed = None, 0

    for line in stdout.splitlines():
        if line.startswith("--- "):
            flush()
            current = line[4:].strip()
        elif line.startswith("+++ ") or line.startswith("@@"):
            continue
        elif line.startswith(("+", "-")):
            changed += 1
    flush()
    return findings
