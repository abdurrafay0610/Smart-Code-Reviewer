"""Signal -> axis routing (Design section 5).

Every deterministic signal has exactly one home. Keeping that policy in a single
function is what actually prevents the three review agents from overlapping - the
tabbed UI only prevents the *perception* of overlap. See Design section 5 "Routing note".
"""

from __future__ import annotations

from ..agents.types import Axis, ToolFinding

# Ruff rule families we deliberately enable, grouped by the axis that owns them.
# Because run() restricts Ruff to exactly these families (--select), prefix routing
# is unambiguous: no other codes can appear.
_READABILITY_RUFF_PREFIXES = ("N", "RET", "SIM")  # naming, return-flow, simplify
_MAINTAINABILITY_RUFF_PREFIXES = ("F", "B", "UP")  # pyflakes, bugbear, pyupgrade
_MAGIC_NUMBER_CODE = "PLR2004"  # magic numbers -> readability


def axis_for(finding: ToolFinding) -> Axis | None:
    """Return the axis that owns a finding, or None if it is unroutable."""
    tool, signal = finding.tool, finding.signal

    if tool == "lizard":
        # Structural metrics; duplication (if ever emitted by lizard) is maintainability.
        return "maintainability" if signal == "duplication" else "structure"
    if tool == "radon":
        return "maintainability"
    if tool == "dup":
        return "maintainability"
    if tool == "ruff-format":
        return "readability"
    if tool == "ruff":
        if signal == _MAGIC_NUMBER_CODE:
            return "readability"
        if signal.startswith(_READABILITY_RUFF_PREFIXES):
            return "readability"
        if signal.startswith(_MAINTAINABILITY_RUFF_PREFIXES):
            return "maintainability"
    return None
