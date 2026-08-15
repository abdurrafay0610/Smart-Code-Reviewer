"""
The three review agents (Design §6).

Each agent is a *presentation specialist* for one axis. It receives only its own
slice of the evidence bundle (§5) plus the project map (§7) — and, for the two
axes drift routes to, any architectural-drift findings (§8) — and turns them
into reviewer-style findings for its UI tab (§9). Because the evidence is
partitioned upstream, the agents cannot overlap.

All three share ``ReviewAgent``, which fixes:
  * the input contract (evidence slice + map + optional drift),
  * the grounding rules (cite every finding; abstain when clean; stay in-axis) —
    the design's principles #3 and #4 made executable in the prompt,
  * the JSON output schema and how it maps to ``AgentResult``.

A concrete agent just declares its axis, a line of axis guidance, the signals it
owns (straight from the §5 tables), and whether drift routes to it. Everything
model-facing that is common lives in the base, so the three stay tiny.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import AgentResponseError, BaseAgent
from .deepseek_client import DeepSeekResponse
from .types import (
    AgentFinding,
    AgentResult,
    Axis,
    DriftFinding,
    ProjectMap,
    Severity,
    ToolFinding,
)

_VALID_SEVERITIES: frozenset[str] = frozenset({"info", "low", "medium", "high"})


@dataclass(frozen=True, slots=True)
class ReviewInput:
    """
    Everything one review agent needs for a single review.

    ``findings`` is this axis's slice of the evidence bundle; ``project_map`` is
    the shared context; ``drift`` is empty unless drift routes to this axis (§8).
    All three are produced upstream and are currently stubbed (``stubs.py``).
    """

    axis: Axis
    findings: list[ToolFinding]
    project_map: ProjectMap
    drift: list[DriftFinding] = field(default_factory=list)


# ---------------------------------------------------------------------------- #
# Shared base
# ---------------------------------------------------------------------------- #
class ReviewAgent(BaseAgent[ReviewInput, AgentResult]):
    """
    Base for the three axis agents. Concrete subclasses set the four class
    attributes below; everything else (prompt scaffolding, parsing) is shared.
    """

    #: Which axis this agent owns.
    AXIS: Axis = "readability"
    #: One or two sentences of axis-specific reviewing guidance.
    AXIS_GUIDANCE: str = ""
    #: The signals this axis owns (from §5) — named in the prompt so the model
    #: knows its remit and stays out of the other tabs.
    OWNED_SIGNALS: tuple[str, ...] = ()
    #: Whether architectural-drift findings route into this axis (§8).
    ACCEPTS_DRIFT: bool = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Give each concrete agent a stable log-context name derived from its axis.
        cls.name = f"{cls.AXIS}-agent"

    # ---- system prompt (shared, composed from the class attributes) --------
    def system_prompt(self) -> str:
        signals = ", ".join(self.OWNED_SIGNALS) or "(none configured)"

        drift_clause = (
            "\n- Some inputs may include ARCHITECTURAL DRIFT findings. Each cites a "
            "ratified invariant, so state the violation as fact, but phrase any fix "
            "as a suggestion (detection and suggestion are different acts)."
            if self.ACCEPTS_DRIFT
            else ""
        )

        return (
            f"You are a senior software engineer writing the {self.AXIS.upper()} section "
            "of an automated pre-review, before a human opens a pull request.\n\n"
            "You are given, as JSON:\n"
            "  1. project_map — prose describing how this codebase is meant to fit "
            "together, plus a list of ratified architectural invariants.\n"
            "  2. evidence — objective findings from deterministic C++ analysers "
            "(clang-tidy, cppcheck, clang-format, lizard). Each has a file path and, "
            "usually, a line number and a measured metric.\n"
            f"{('  3. architectural_drift — invariant violations routed to this axis.' + chr(10)) if self.ACCEPTS_DRIFT else ''}"
            "\n"
            "Your job is to interpret, prioritise, and explain this evidence the way "
            "a senior reviewer would — and to make the qualitative calls the tools "
            "cannot (e.g. whether a name is actually clear, not merely conformant). "
            "You are NOT hunting for new issues from a blank slate.\n\n"
            "Rules:\n"
            "- GROUND EVERY finding in the provided inputs. Each finding MUST carry "
            "at least one citation: a \"path:line\" taken from the evidence, or "
            "\"invariant:<id>\" for a drift finding. If you cannot cite it from the "
            "inputs, do not raise it. Never invent file names, line numbers, metrics, "
            "or issues that are not present in the inputs.\n"
            f"- Stay strictly within the {self.AXIS} axis. The signals you own are: "
            f"{signals}. Do not comment on other axes; they are handled by other agents.\n"
            "- Abstaining is a valid, good outcome. If the evidence is empty or "
            "benign, return an empty \"findings\" list and say so in \"summary\". Do "
            "NOT manufacture problems to look thorough.\n"
            "- Use project_map for architectural context (e.g. a file's stated "
            "responsibility), not as a source of new issues beyond its invariants."
            f"{drift_clause}\n\n"
            "Return STRICT JSON only — no markdown, no text outside the JSON object — "
            "matching this schema exactly:\n"
            "{\n"
            '  "summary": string,        // 1-3 sentences: the headline for this axis\n'
            '  "abstained": boolean,     // true when there are no real concerns\n'
            '  "findings": [\n'
            "    {\n"
            '      "title": string,      // short and specific\n'
            '      "detail": string,     // plain-English: what it is and why it matters\n'
            '      "severity": "info" | "low" | "medium" | "high",\n'
            '      "citations": [string],// e.g. ["src/foo.cpp:42"] or ["invariant:parser-no-io"]\n'
            '      "suggestion": string  // optional: how a senior reviewer would fix it\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "Severity guide: high = clear defect risk or will bite soon; medium = "
            "should fix; low = minor; info = worth noting."
        )

    # ---- user message (shared) ---------------------------------------------
    def build_user_input(self, payload: ReviewInput) -> str:
        doc: dict[str, object] = {
            "axis": payload.axis,
            "project_map": {
                "prose": payload.project_map.prose,
                "invariants": [
                    {"id": inv.id, "rule": inv.rule}
                    for inv in payload.project_map.invariants
                ],
                "file_roles": [
                    {"path": role.path, "responsibility": role.responsibility}
                    for role in payload.project_map.file_roles
                    if role.responsibility
                ],
            },
            "evidence": [self._finding_json(f) for f in payload.findings],
        }

        if self.ACCEPTS_DRIFT and payload.drift:
            doc["architectural_drift"] = [
                {
                    "invariant_id": d.invariant_id,
                    "invariant_rule": d.invariant_rule,
                    "location": d.location(),
                    "explanation": d.explanation,
                }
                for d in payload.drift
            ]

        instruction = (
            f"Produce the {payload.axis} review as STRICT JSON per the schema. "
            "Cite every finding from the inputs below. If the evidence shows no "
            f"real {payload.axis} concerns, abstain with an empty findings list."
        )

        return f"{instruction}\n\nINPUTS:\n{json.dumps(doc, indent=2)}"

    @staticmethod
    def _finding_json(finding: ToolFinding) -> dict[str, object]:
        """Compact, citable JSON for one evidence item (omitting empty fields)."""
        data: dict[str, object] = {
            "tool": finding.tool,
            "signal": finding.signal,
            "location": finding.where(),
            "message": finding.message,
        }
        if finding.metric is not None:
            data["metric"] = finding.metric
        if finding.threshold is not None:
            data["threshold"] = finding.threshold
        if finding.severity is not None:
            data["tool_severity"] = finding.severity
        return data

    # ---- parsing (shared) --------------------------------------------------
    def parse_payload(self, obj: object, response: DeepSeekResponse) -> AgentResult:
        if not isinstance(obj, dict):
            raise AgentResponseError(
                "Expected a JSON object at the top level.",
                raw_content=response.content,
            )

        raw_findings = obj.get("findings", [])
        if raw_findings is None:
            raw_findings = []
        if not isinstance(raw_findings, list):
            raise AgentResponseError(
                "'findings' must be a list.",
                raw_content=response.content,
            )

        findings: list[AgentFinding] = []
        for raw in raw_findings:
            if not isinstance(raw, dict):
                continue

            severity = str(raw.get("severity", "info")).strip().lower()
            if severity not in _VALID_SEVERITIES:
                severity = "info"

            raw_citations = raw.get("citations", []) or []
            citations = (
                [str(c).strip() for c in raw_citations if str(c).strip()]
                if isinstance(raw_citations, list)
                else []
            )

            suggestion_raw = raw.get("suggestion")
            suggestion = (
                str(suggestion_raw).strip()
                if isinstance(suggestion_raw, str) and suggestion_raw.strip()
                else None
            )

            findings.append(
                AgentFinding(
                    title=str(raw.get("title", "")).strip() or "(untitled finding)",
                    detail=str(raw.get("detail", "")).strip(),
                    severity=severity,  # type: ignore[arg-type]
                    citations=citations,
                    suggestion=suggestion,
                )
            )

        abstained = bool(obj.get("abstained", len(findings) == 0))

        summary = str(obj.get("summary", "")).strip()
        if not summary:
            summary = (
                f"No {self.AXIS} concerns found in the provided evidence."
                if abstained
                else f"{len(findings)} {self.AXIS} finding(s)."
            )

        return AgentResult(
            axis=self.AXIS,
            summary=summary,
            findings=findings,
            abstained=abstained,
            model=response.model,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
        )


# ---------------------------------------------------------------------------- #
# Concrete agents — one per axis (§5 tables define the owned signals)
# ---------------------------------------------------------------------------- #
class ReadabilityAgent(ReviewAgent):
    AXIS = "readability"
    AXIS_GUIDANCE = (
        "Explain naming, magic-number, brace, control-flow, and formatting "
        "findings in human terms, and judge whether names are genuinely clear "
        "rather than merely convention-conformant."
    )
    OWNED_SIGNALS = (
        "identifier naming",
        "magic numbers",
        "missing braces",
        "redundant control flow (else-after-return, boolean simplification)",
        "formatting drift (clang-format)",
    )
    ACCEPTS_DRIFT = False


class StructureAgent(ReviewAgent):
    AXIS = "structure"
    AXIS_GUIDANCE = (
        "Interpret complexity, length, parameter-count, and nesting numbers in "
        "terms of decomposition and single-responsibility, and fold in any "
        "structural architectural drift."
    )
    OWNED_SIGNALS = (
        "cyclomatic complexity (CCN)",
        "function length (NLOC)",
        "parameter count",
        "cognitive complexity / nesting",
        "decomposition",
    )
    ACCEPTS_DRIFT = True


class MaintainabilityAgent(ReviewAgent):
    AXIS = "maintainability"
    AXIS_GUIDANCE = (
        "Interpret warning density, outdated idioms, duplication, and the "
        "maintainability index in terms of change-amplification and future "
        "cost, and fold in any maintainability-related architectural drift."
    )
    OWNED_SIGNALS = (
        "static-analysis warnings (cppcheck)",
        "outdated idioms (modernize-*)",
        "code duplication",
        "composite maintainability index",
    )
    ACCEPTS_DRIFT = True


#: Convenience: the three agent classes keyed by axis.
REVIEW_AGENTS: dict[Axis, type[ReviewAgent]] = {
    "readability": ReadabilityAgent,
    "structure": StructureAgent,
    "maintainability": MaintainabilityAgent,
}

def __init__(self, *, language: str = "", **kwargs):
    self.language = language
    super().__init__(**kwargs)