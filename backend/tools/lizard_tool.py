"""lizard runner - the entire Structure axis (Design section 5, cross-language).

lizard is language-agnostic: the same call reports cyclomatic complexity, line count,
parameter count, and nesting depth for Python, C++, Java, JavaScript and more. It is
used through its Python API (no subprocess). This pass restricts input to .py files;
broadening the adapter to other languages is a one-line change to SUPPORTED_SUFFIXES.

Findings are threshold-gated so the evidence bundle holds smells worth a reviewer's
attention rather than raw metrics for every function. The measured value and the gate
travel on each finding (metric / threshold) so the agent can calibrate severity itself.
"""

from __future__ import annotations

from pathlib import Path

import lizard

from ..agents.types import ToolFinding

CCN_THRESHOLD = 10  # cyclomatic complexity: > this is a smell
NLOC_THRESHOLD = 60  # function length in lines
PARAM_THRESHOLD = 4  # parameter count
NESTING_THRESHOLD = 4  # maximum block nesting depth
SUPPORTED_SUFFIXES = {".py"}  # cross-language: add ".js", ".java", ".cpp", ... here


def run(files: list[Path], rel_to: Path) -> list[ToolFinding]:
    findings: list[ToolFinding] = []
    for path in files:
        if path.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            info = lizard.analyze_file(str(path))
        except Exception:
            continue  # unparsable file: stay silent rather than raise
        rel = str(path.relative_to(rel_to))
        for fn in info.function_list:
            loc = {"path": rel, "line": fn.start_line, "end_line": fn.end_line}
            if fn.cyclomatic_complexity > CCN_THRESHOLD:
                findings.append(
                    ToolFinding(
                        tool="lizard",
                        signal="ccn",
                        message=f"Function `{fn.name}` has cyclomatic complexity "
                        f"{fn.cyclomatic_complexity}.",
                        metric=fn.cyclomatic_complexity,
                        threshold=CCN_THRESHOLD,
                        **loc,
                    )
                )
            if fn.nloc > NLOC_THRESHOLD:
                findings.append(
                    ToolFinding(
                        tool="lizard",
                        signal="nloc",
                        message=f"Function `{fn.name}` is {fn.nloc} lines long.",
                        metric=fn.nloc,
                        threshold=NLOC_THRESHOLD,
                        **loc,
                    )
                )
            if fn.parameter_count > PARAM_THRESHOLD:
                findings.append(
                    ToolFinding(
                        tool="lizard",
                        signal="parameter-count",
                        message=f"Function `{fn.name}` takes {fn.parameter_count} "
                        f"parameters.",
                        metric=fn.parameter_count,
                        threshold=PARAM_THRESHOLD,
                        **loc,
                    )
                )
            depth = getattr(fn, "max_nesting_depth", None)
            if depth is not None and depth > NESTING_THRESHOLD:
                findings.append(
                    ToolFinding(
                        tool="lizard",
                        signal="nesting",
                        message=f"Function `{fn.name}` nests {depth} levels deep.",
                        metric=depth,
                        threshold=NESTING_THRESHOLD,
                        **loc,
                    )
                )
    return findings
