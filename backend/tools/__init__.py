"""Deterministic tool layer - the Python adapter (Design section 5).

The single language-dependent component in the system. Cross-language metrics come from
lizard; Python-specific signals from Ruff and radon; duplication from a simple token
check. Everything above this layer (the evidence bundle, the agents, drift, synthesis)
is language-neutral.
"""

from .runner import partition_by_axis, run_all_tools
from .routing import axis_for

__all__ = ["run_all_tools", "partition_by_axis", "axis_for"]
