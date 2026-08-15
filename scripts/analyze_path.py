#!/usr/bin/env python3
"""Run the deterministic tool layer on a local path and print the evidence bundle.

A convenience entry point for dogfooding: it exercises the exact tools the Phase B
review uses (Design section 5), but on files already on disk - no git branch, no repo
connection. Point it at the project's own backend to see the reviewer review itself:

    python scripts/analyze_path.py backend

This is deterministic output only (the LLM agents are not invoked); it is what the
agents would receive as evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.tools import partition_by_axis, run_all_tools  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python scripts/analyze_path.py <file-or-directory>")
        return 2
    root = Path(argv[1]).resolve()
    if not root.exists():
        print(f"no such path: {root}")
        return 2

    if root.is_file():
        files, rel_to = [root], root.parent
    else:
        files, rel_to = sorted(root.rglob("*.py")), root
    if not files:
        print("no .py files found")
        return 0

    findings = run_all_tools(files, rel_to)
    bundle = partition_by_axis(findings)
    total = len(findings)
    print(f"{total} finding(s) across {len(files)} file(s) under {root}\n")
    for axis in ("readability", "structure", "maintainability"):
        items = bundle.for_axis(axis)
        print(f"== {axis.upper()} ({len(items)}) ==")
        for f in sorted(items, key=lambda x: (x.path, x.line or 0)):
            metric = f" [{f.metric}]" if f.metric is not None else ""
            print(f"  {f.where():36} {f.signal:16} {f.message}{metric}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
