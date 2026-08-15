"""Code duplication - the "simple token check" the design sanctions in place of
lizard's duplicate extension (Design section 5, Maintainability).

lizard's -Eduplicate proved unreliable (it missed obvious clones) and emits text that
is awkward to parse, so this uses the design's explicitly-allowed fallback: normalise
each file's significant lines, hash sliding windows, and flag windows whose content
recurs. Overlapping duplicate windows are coalesced into one region per file so a long
clone yields a single finding, not dozens.

Scope is the changed-file set passed in (within and among those files). Detecting a new
block that duplicates *unchanged* code elsewhere in the repo is a noted refinement.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path

from ..agents.types import ToolFinding

MIN_DUP_LINES = 6  # a run of this many identical significant lines counts as a clone
SUPPORTED_SUFFIXES = {".py"}


def _significant_lines(text: str) -> list[tuple[int, str]]:
    """(line_number, normalised_text) for non-blank, non-comment-only lines."""
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append((i, " ".join(stripped.split())))
    return out


def _coalesce(lines: list[int]) -> list[tuple[int, int]]:
    """Merge a sorted list of line numbers into contiguous (start, end) ranges."""
    ranges: list[tuple[int, int]] = []
    for ln in lines:
        if ranges and ln <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], ln))
        else:
            ranges.append((ln, ln))
    return ranges


def run(files: list[Path], rel_to: Path) -> list[ToolFinding]:
    # hash of a normalised window -> occurrences [(relpath, start_line, end_line), ...]
    windows: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
    for path in files:
        if path.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(path.relative_to(rel_to))
        sig = _significant_lines(text)
        for j in range(len(sig) - MIN_DUP_LINES + 1):
            block = sig[j : j + MIN_DUP_LINES]
            body = "\n".join(text for _, text in block)
            digest = hashlib.sha1(body.encode()).hexdigest()
            windows[digest].append((rel, block[0][0], block[-1][0]))

    # Per file: which lines sit inside *any* duplicated window, and where the partners are.
    covered: dict[str, set[int]] = defaultdict(set)
    partners: dict[str, set[str]] = defaultdict(set)
    for occ in windows.values():
        if len(occ) < 2:
            continue
        for rel, start, end in occ:
            covered[rel].update(range(start, end + 1))
            for r2, s2, _ in occ:
                if (r2, s2) != (rel, start):
                    partners[rel].add(f"{r2}:{s2}")

    findings: list[ToolFinding] = []
    for rel, lines in covered.items():
        for start, end in _coalesce(sorted(lines)):
            # Partner hints for this region, excluding lines inside the region itself.
            elsewhere = [
                p
                for p in sorted(partners[rel])
                if not (
                    p.startswith(f"{rel}:") and start <= int(p.rsplit(":", 1)[1]) <= end
                )
            ][:3]
            where = ", ".join(elsewhere) if elsewhere else "another location"
            findings.append(
                ToolFinding(
                    tool="dup",
                    signal="duplication",
                    path=rel,
                    line=start,
                    end_line=end,
                    message=f"Lines {start}-{end} duplicate code elsewhere in the change "
                    f"set (e.g. {where}).",
                    metric=end - start + 1,
                )
            )
    return findings
