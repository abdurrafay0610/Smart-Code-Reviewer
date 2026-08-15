"""
The map "climb" LLM rungs (Design §7.2).

Where the review agents (``review_agents.py``) interpret evidence for the UI,
these three build the *map itself* — and they obey the same two principles:
principle #1 (the model is only for judgement; trees, languages, and imports are
already computed deterministically in ``source_scan``) and principle #2 (one
bounded decision per call). Each rung subclasses ``BaseAgent`` so every model
call still funnels through ``query_deepseek``.

The rungs, each consuming the *verified* output of the one below:

    ResponsibilityAgent   one file  -> one-line responsibility        (rung 2b)
    ArchitectureAgent     role table -> layers/modules/deps + prose   (rung 3)
    InvariantAgent        architecture -> candidate invariants        (rung 4)

Grounding is enforced in every prompt: describe only what the inputs show, never
invent a file, module, or dependency. Rung 3 reads the *role table* (a compact
digest of rung 2), not raw source, which keeps the one genuine synthesis call
in-window and rooted in verified facts. Rung 4's output is explicitly a set of
*candidates* — a human ratifies them (§7.3) before drift ever cites them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .base import AgentResponseError, BaseAgent
from .deepseek_client import DeepSeekResponse
from .types import FileRole, Invariant

#: A single file's source is capped before it goes to the model. Responsibility
#: is judged from the top of a file (imports, definitions, docstring), so a head
#: slice is sufficient and keeps even a large file comfortably in-window.
_MAX_SOURCE_CHARS = 16_000


def _clip(source: str) -> str:
    if len(source) <= _MAX_SOURCE_CHARS:
        return source
    return source[:_MAX_SOURCE_CHARS] + "\n… [truncated]"


# ============================================================================ #
# Rung 2b — per-file responsibility
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class ResponsibilityInput:
    """One file for the responsibility rung: path + language + its source.

    ``imports`` (from ``source_scan``) is passed as a hint only; the judgement is
    grounded in the source. Code fetches the file, the model only judges it.
    """

    path: str
    language: str
    source: str
    imports: list[str] = field(default_factory=list)


class ResponsibilityAgent(BaseAgent[ResponsibilityInput, FileRole]):
    """One file in, one-line responsibility out (rung 2b).

    The highest-volume rung (one call per source file) and the simplest
    judgement, so it defaults to the fast model with thinking off and a tight
    token budget. Callers can override any of these via kwargs.
    """

    name = "map-responsibility"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("model", "deepseek-v4-flash")
        kwargs.setdefault("thinking", False)
        kwargs.setdefault("max_tokens", 512)
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def system_prompt(self) -> str:
        return (
            "You are a senior engineer summarising one source file for a project "
            "map. Given a single file, state in ONE sentence what that file is "
            "responsible for — its role in the codebase, not a line-by-line "
            "description.\n\n"
            "Rules:\n"
            "- Ground the sentence in what the code actually does. Do not "
            "speculate about code that isn't shown.\n"
            "- Describe responsibility (\"parses config into typed settings\"), "
            "not mechanics (\"defines a function called load\").\n"
            "- Be concise and specific. No file name, no preamble.\n\n"
            'Return ONLY JSON: {"responsibility": "<one sentence>"}'
        )

    def build_user_input(self, payload: ResponsibilityInput) -> str:
        imports = ", ".join(payload.imports) if payload.imports else "(none)"
        return (
            f"path: {payload.path}\n"
            f"language: {payload.language}\n"
            f"imports: {imports}\n\n"
            "source:\n"
            f"{_clip(payload.source)}"
        )

    def parse_payload(self, obj: object, response: DeepSeekResponse) -> FileRole:
        if not isinstance(obj, dict):
            raise AgentResponseError(
                "responsibility response was not a JSON object",
                raw_content=response.content,
            )
        responsibility = str(obj.get("responsibility", "")).strip()
        # path/language are ours (deterministic), not the model's — we only take
        # the responsibility from it. imports live on the on-disk record, not the
        # FileRole dataclass, so they're re-attached by the orchestrator.
        return FileRole(
            path="",  # filled in by the caller, which knows the file
            language="",
            responsibility=responsibility,
        )


# ============================================================================ #
# Rung 3 — architecture inference (the one genuine synthesis call)
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class ArchitectureResult:
    """Rung 3 output: a prose description plus a structured architecture dict."""

    prose: str
    architecture: dict


@dataclass(frozen=True, slots=True)
class ArchitectureInput:
    """The role table (rung 2 output) — the only thing rung 3 reads.

    Each entry is ``{path, language, responsibility, imports}``. No raw source:
    the digest is what keeps this synthesis call in-window and grounded.
    """

    file_roles: list[dict]


class ArchitectureAgent(BaseAgent[ArchitectureInput, ArchitectureResult]):
    """Role table in, inferred architecture + prose out (rung 3).

    This is the hard reasoning step, so it uses the strong model with thinking
    on and a larger budget.
    """

    name = "map-architecture"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("model", "deepseek-v4-pro")
        kwargs.setdefault("thinking", True)
        kwargs.setdefault("max_tokens", 4096)
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def system_prompt(self) -> str:
        return (
            "You are a software architect inferring the structure of a codebase "
            "from a table of per-file roles. Each row gives a file's path, "
            "language, one-line responsibility, and the modules it imports. The "
            "import edges reveal how files depend on one another.\n\n"
            "Infer the codebase's layers/modules and how they relate, then "
            "describe it.\n\n"
            "Rules:\n"
            "- Use ONLY the table. Every layer, module, and dependency you name "
            "must be traceable to the paths, responsibilities, or imports given. "
            "Never invent files or relationships.\n"
            "- Group files into meaningful modules/layers by directory and by "
            "responsibility; describe the dependency direction between them.\n"
            "- The prose is for a human reviewer: the shape of the system, the "
            "key modules, and how they fit together.\n\n"
            "Return ONLY JSON with this shape:\n"
            "{\n"
            '  "prose": "<a few short paragraphs describing the architecture>",\n'
            '  "layers": [{"name": "<layer>", "responsibility": "<what it does>", '
            '"paths": ["<dir or file>"]}],\n'
            '  "modules": [{"name": "<module>", "responsibility": "<what it does>", '
            '"paths": ["<dir or file>"]}],\n'
            '  "dependencies": [{"from": "<module>", "to": "<module>", '
            '"via": "<why: e.g. imports>"}]\n'
            "}"
        )

    def build_user_input(self, payload: ArchitectureInput) -> str:
        return "file role table (JSON):\n" + json.dumps(payload.file_roles, indent=2)

    def parse_payload(
        self, obj: object, response: DeepSeekResponse
    ) -> ArchitectureResult:
        if not isinstance(obj, dict):
            raise AgentResponseError(
                "architecture response was not a JSON object",
                raw_content=response.content,
            )
        prose = str(obj.get("prose", "")).strip()
        architecture = {
            "layers": obj.get("layers", []),
            "modules": obj.get("modules", []),
            "dependencies": obj.get("dependencies", []),
        }
        return ArchitectureResult(prose=prose, architecture=architecture)


# ============================================================================ #
# Rung 4 — candidate invariants
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class InvariantInput:
    """What rung 4 proposes rules from: the inferred architecture + role table.

    Prose gives the intent; the structured architecture and roles give the
    concrete modules a rule can be attached to.
    """

    prose: str
    architecture: dict
    file_roles: list[dict]


class InvariantAgent(BaseAgent[InvariantInput, list[Invariant]]):
    """Architecture in, a small set of *candidate* invariants out (rung 4).

    The output is deliberately unratified: a human approves/edits/rejects each
    one (§7.3) before the drift check may cite it. Careful rule proposal, so
    strong model + thinking on.
    """

    name = "map-invariants"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("model", "deepseek-v4-pro")
        kwargs.setdefault("thinking", True)
        kwargs.setdefault("max_tokens", 2048)
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def system_prompt(self) -> str:
        return (
            "You are a staff engineer proposing architectural INVARIANTS for a "
            "codebase — a small set of explicit, checkable rules that capture how "
            "the code is meant to fit together. A later automated check will cite "
            "these by name against incoming changes, so each must be concrete "
            "enough to test a diff against.\n\n"
            "Good invariants are things like: layering/dependency rules "
            "(\"ui/ may depend on core/, never the reverse\"), I/O ownership "
            "(\"only net/ performs network I/O\"), per-module responsibility "
            "(\"parser/ does tokens->AST, no I/O\"), and naming/ownership "
            "conventions.\n\n"
            "Rules:\n"
            "- Propose FEW, STRONG rules (roughly 3-8). A plausible-but-wrong "
            "invariant is worse than none, because it will fail good code.\n"
            "- Ground every rule in the provided architecture and roles. Only "
            "reference modules/layers that appear in the inputs.\n"
            "- Each rule gets a short stable id (kebab-case), the rule itself in "
            "one sentence, and a one-line rationale.\n"
            "- These are CANDIDATES for human review; prefer rules a reviewer can "
            "clearly accept or reject.\n\n"
            "Return ONLY JSON:\n"
            '{"invariants": [{"id": "<kebab-id>", "rule": "<one sentence>", '
            '"rationale": "<why it matters>"}]}'
        )

    def build_user_input(self, payload: InvariantInput) -> str:
        return (
            "architecture prose:\n"
            f"{payload.prose}\n\n"
            "architecture (JSON):\n"
            f"{json.dumps(payload.architecture, indent=2)}\n\n"
            "file role table (JSON):\n"
            f"{json.dumps(payload.file_roles, indent=2)}"
        )

    def parse_payload(
        self, obj: object, response: DeepSeekResponse
    ) -> list[Invariant]:
        if not isinstance(obj, dict) or not isinstance(obj.get("invariants"), list):
            raise AgentResponseError(
                'invariant response missing "invariants" array',
                raw_content=response.content,
            )
        invariants: list[Invariant] = []
        for item in obj["invariants"]:
            if not isinstance(item, dict):
                continue
            rule = str(item.get("rule", "")).strip()
            if not rule:
                continue
            invariants.append(
                Invariant(
                    id=str(item.get("id", "")).strip(),
                    rule=rule,
                    rationale=str(item.get("rationale", "")).strip(),
                    ratified=False,  # candidates only — §7.3 ratifies later
                )
            )
        return invariants