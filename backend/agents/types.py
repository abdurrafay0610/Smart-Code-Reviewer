"""
Shared data shapes for the review agents (Design §5, §6, §8).

Two families of shapes live here:

* INPUTS the agents consume — the deterministic ``EvidenceBundle`` (§5) and the
  ``ProjectMap`` (§7). These are produced elsewhere (the tool layer and the map
  engine) and are currently STUBBED (see ``stubs.py``). The agents don't care
  whether the data is real or stubbed as long as it has these shapes, which is
  exactly what makes the stubs swappable later.

* OUTPUTS the agents produce — a normalized ``AgentResult`` per axis, ready for
  the UI tabs (§9). Each finding carries ``citations`` so the "no claim without
  a citation" rule (§2, principle 3) is visible in the result itself.

These are plain dataclasses, deliberately separate from the Pydantic API models
in ``backend/models.py``: the HTTP contract shouldn't be coupled to the agents'
internal working shapes yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Axis = Literal["readability", "structure", "maintainability"]
Severity = Literal["info", "low", "medium", "high"]


# ============================================================================ #
# INPUTS
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class ToolFinding:
    """
    One objective, line-numbered finding from a deterministic analyser (§5).

    This is the atom of the evidence bundle. Every field except ``message`` maps
    to something a tool actually reports, which is why an agent can always cite
    it by ``path:line``.
    """

    tool: str  # "clang-tidy" | "cppcheck" | "clang-format" | "lizard" | ...
    signal: str  # e.g. "readability-magic-numbers", "ccn", "nloc", "modernize-use-auto"
    path: str
    message: str
    line: int | None = None
    end_line: int | None = None
    metric: float | int | None = None  # measured value (e.g. CCN = 23)
    threshold: float | int | None = None  # the limit it exceeded (e.g. 15)
    severity: Severity | None = None  # tool-suggested severity, if any

    def where(self) -> str:
        """A compact ``path:line`` citation string (``path`` alone if no line)."""
        return f"{self.path}:{self.line}" if self.line is not None else self.path


@dataclass(frozen=True, slots=True)
class DriftFinding:
    """
    A ratified-invariant violation from the drift check (§8), routed to an axis.

    Detection is grounded (it names a ratified invariant), so it is stated as
    fact; any accompanying fix is a softer suggestion (§8).
    """

    invariant_id: str
    invariant_rule: str
    explanation: str
    path: str | None = None
    line: int | None = None

    def citation(self) -> str:
        return f"invariant:{self.invariant_id}"

    def location(self) -> str | None:
        if self.path is None:
            return None
        return f"{self.path}:{self.line}" if self.line is not None else self.path


@dataclass(frozen=True, slots=True)
class Invariant:
    """One checkable architectural rule from the map (§7.1)."""

    id: str
    rule: str
    rationale: str = ""
    ratified: bool = False


@dataclass(frozen=True, slots=True)
class FileRole:
    """A file's language + one-line responsibility (rung 2 of the climb, §7.2)."""

    path: str
    language: str = ""
    responsibility: str = ""


@dataclass(frozen=True, slots=True)
class ProjectMap:
    """
    The codebase context file (§7): prose + ratified invariants (+ roles).

    ``from_dict`` builds this from the ``map.json`` shape written by
    ``map_service`` and is tolerant of the current empty stub — an unbuilt map
    simply yields empty prose / invariants / roles.
    """

    prose: str = ""
    invariants: list[Invariant] = field(default_factory=list)
    file_roles: list[FileRole] = field(default_factory=list)
    architecture: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProjectMap":
        data = data or {}

        invariants = [
            Invariant(
                id=str(item.get("id", "")),
                rule=str(item.get("rule", "")),
                rationale=str(item.get("rationale", "")),
                ratified=bool(item.get("ratified", False)),
            )
            for item in (data.get("invariants") or [])
            if isinstance(item, dict)
        ]

        file_roles = [
            FileRole(
                path=str(item.get("path", "")),
                language=str(item.get("language", "")),
                responsibility=str(item.get("responsibility", "")),
            )
            for item in (data.get("file_roles") or [])
            if isinstance(item, dict)
        ]

        return cls(
            prose=str(data.get("prose", "") or ""),
            invariants=invariants,
            file_roles=file_roles,
            architecture=dict(data.get("architecture") or {}),
        )


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """
    Tool findings partitioned by axis (§5).

    The partition — not the tabbed UI — is what actually stops the three agents
    from overlapping: each signal has exactly one home, so each agent only ever
    sees its own slice.
    """

    readability: list[ToolFinding] = field(default_factory=list)
    structure: list[ToolFinding] = field(default_factory=list)
    maintainability: list[ToolFinding] = field(default_factory=list)

    def for_axis(self, axis: Axis) -> list[ToolFinding]:
        return getattr(self, axis)


# ============================================================================ #
# OUTPUTS
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class AgentFinding:
    """
    One reviewer-style finding for a tab (§6).

    ``citations`` is non-optional in spirit: an agent is instructed never to
    raise a finding it cannot cite. Each entry is either a ``path:line`` (from a
    tool) or ``invariant:<id>`` (from drift).
    """

    title: str
    detail: str
    severity: Severity
    citations: list[str] = field(default_factory=list)
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class AgentResult:
    """
    Normalized output of one review agent (§6), ready for a UI tab (§9).

    The token/model fields are carried through for transparency — the design
    treats visible rigour as a feature, and surfacing "this verdict cost N
    tokens on model X" is part of that.
    """

    axis: Axis
    summary: str
    findings: list[AgentFinding] = field(default_factory=list)
    abstained: bool = False
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
