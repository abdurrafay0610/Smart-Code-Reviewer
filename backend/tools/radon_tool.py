"""radon runner - the composite maintainability index (Design section 5).

The Maintainability Index the C++ design could only approximate is first-class here:
radon computes it directly from SLOC + cyclomatic complexity + Halstead volume on the
same 0-100 shifted scale Visual Studio uses. Used through radon's Python API.

Only files below the threshold produce a finding (rank B or C, i.e. < 20), which keeps
this signal quiet on healthy files and meaningful when it fires.
"""

from __future__ import annotations

from pathlib import Path

from radon.metrics import mi_rank, mi_visit

from ..agents.types import ToolFinding

MI_THRESHOLD = 20  # radon rank A is >= 20; below that is B/C ("yellow"/"red")
SUPPORTED_SUFFIXES = {".py"}


def run(files: list[Path], rel_to: Path) -> list[ToolFinding]:
    findings: list[ToolFinding] = []
    for path in files:
        if path.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            mi = mi_visit(src, multi=True)
        except Exception:
            continue  # syntax error or unreadable: skip
        if mi < MI_THRESHOLD:
            findings.append(
                ToolFinding(
                    tool="radon",
                    signal="maintainability-index",
                    path=str(path.relative_to(rel_to)),
                    line=None,
                    message=f"File maintainability index is {mi:.0f} (rank {mi_rank(mi)}); "
                    f"below {MI_THRESHOLD} is costly to maintain.",
                    metric=round(mi, 1),
                    threshold=MI_THRESHOLD,
                )
            )
    return findings
