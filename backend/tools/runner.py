"""Runs every tool in the Python adapter and partitions the result by axis.

review_service calls run_all_tools() on the materialised changed files, then
partition_by_axis() to produce the EvidenceBundle the agents consume. Nothing here
knows about git - the caller is responsible for putting real files on disk first.
"""

from __future__ import annotations

from pathlib import Path

from ..agents.types import EvidenceBundle, ToolFinding
from . import dup_tool, lizard_tool, radon_tool, ruff_tool
from .routing import axis_for

# The Python adapter. To add a language-specific tool, append its module here; to add a
# whole new language, broaden each tool's SUPPORTED_SUFFIXES.
_TOOLS = (ruff_tool, lizard_tool, radon_tool, dup_tool)


def run_all_tools(files: list[Path], rel_to: Path, *, logger=None) -> list[ToolFinding]:
    """Run every tool on `files`, returning findings with paths relative to rel_to."""
    paths = [Path(f) for f in files]
    findings: list[ToolFinding] = []
    for tool in _TOOLS:
        name = tool.__name__.rsplit(".", 1)[-1]
        try:
            produced = tool.run(paths, rel_to)
        except Exception as exc:  # one tool failing must not sink the whole review
            if logger is not None:
                logger.log(f"tool {name} failed: {exc}")
            continue
        if logger is not None:
            logger.log(f"tool {name}: {len(produced)} finding(s)")
        findings += produced
    return findings


def partition_by_axis(findings: list[ToolFinding]) -> EvidenceBundle:
    """Route each finding to exactly one axis (Design section 5)."""
    buckets: dict[str, list[ToolFinding]] = {
        "readability": [],
        "structure": [],
        "maintainability": [],
    }
    for finding in findings:
        axis = axis_for(finding)
        if axis is not None:
            buckets[axis].append(finding)
    return EvidenceBundle(**buckets)
