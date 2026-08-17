"""
The map "climb" LLM rungs (Design §7.2).

Where the review agents (``review_agents.py``) interpret evidence for the UI,
these build the *map itself* — obeying the same two principles: the model is only
for judgement (trees, languages, imports, and now the module dependency graph are
computed deterministically), and one bounded decision per call.

The rungs, each consuming the *verified* output of the one below:

    ResponsibilityAgent    one file  -> one-line responsibility        (rung 2b)
    ArchitectureAgent      roles + dep graph -> layers/modules         (rung 3a)
    ArchitectureProseAgent structure -> human-readable prose           (rung 3b)
    InvariantAgent         structure -> candidate invariants           (rung 4)

Rung 3 is deliberately split. The dependency graph is now supplied as ground
truth (``module_graph``), so the model no longer infers it from every file's
imports — it only names the layers and judges their direction. That, plus
splitting the prose into its own call, keeps each call's input *and* output
small, which is what stops a single call from exhausting the token budget
(reasoning tokens count against ``max_tokens``, so a big synthesis call with
thinking on can spend the whole budget before it answers). Rung 4 likewise reads
the compact structure, not the imports-laden file table.
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


def _roles_for_prompt(file_roles: list[dict]) -> list[dict]:
    """A compact role table for the synthesis rungs: path + language + role only.

    Per-file imports are deliberately dropped here — the module dependency graph
    now carries the dependency information in a far smaller form.
    """
    return [
        {
            "path": r.get("path", ""),
            "language": r.get("language", ""),
            "responsibility": r.get("responsibility", ""),
        }
        for r in file_roles
    ]


def _graph_for_prompt(graph: dict) -> dict:
    """Slim the dependency graph for a prompt: module *names* + edges only.

    The per-module file lists duplicate the paths already in the role table, so
    they're dropped from the prompt (the full graph is still stored on disk).
    """
    return {
        "modules": [m.get("name", "") for m in graph.get("modules", [])],
        "edges": graph.get("edges", []),
    }


def _architecture_for_prompt(architecture: dict) -> dict:
    """Slim the assembled architecture the same way (module names, not paths)."""
    return {
        "layers": architecture.get("layers", []),
        "modules": [m.get("name", "") for m in architecture.get("modules", [])],
        "dependencies": architecture.get("dependencies", []),
    }


# ============================================================================ #
# Rung 2b — per-file responsibility (unchanged)
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
        kwargs.setdefault("max_token_ceiling", 2048)
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
        # path/language are ours (deterministic); we only take the responsibility.
        return FileRole(path="", language="", responsibility=responsibility)


# ============================================================================ #
# Rung 3a — architecture STRUCTURE (dependencies supplied deterministically)
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class ArchitectureStructure:
    """Rung 3a output: the inferred layers. Modules + dependencies are attached
    deterministically by the orchestrator, so the model never emits them."""

    layers: list


@dataclass(frozen=True, slots=True)
class ArchitectureInput:
    """What rung 3a reads: a compact role table + the deterministic dep graph.

    No raw source and no per-file imports — the graph carries the dependency
    facts, so this call's input stays small and it reasons much less.
    """

    file_roles: list[dict]
    dependency_graph: dict  # {"modules": [...], "edges": [...]} from module_graph


class ArchitectureAgent(BaseAgent[ArchitectureInput, ArchitectureStructure]):
    """Roles + dependency graph in, named layers out (rung 3a).

    The dependencies are given, so the model only groups modules into layers and
    judges the layering direction — a much smaller job than before. Kept on the
    strong model with thinking on, but with generous output headroom so reasoning
    can't starve the answer.
    """

    name = "map-architecture"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("model", "deepseek-v4-pro")
        kwargs.setdefault("thinking", True)
        kwargs.setdefault("max_tokens", 8192)
        kwargs.setdefault("max_token_ceiling", 32768)  # NEW: 8192 -> 16384 -> 32768
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def system_prompt(self) -> str:
        return (
            "You are a software architect. You are given a codebase as a compact "
            "table of per-file roles and a MODULE DEPENDENCY GRAPH that has "
            "already been computed for you (its edges are facts, not guesses — "
            "each is a real import from one module to another).\n\n"
            "Your one job: group the modules into architectural LAYERS and "
            "characterise them. Do NOT recompute dependencies — they are given.\n\n"
            "Rules:\n"
            "- Use ONLY the provided modules and edges. Every layer must be made "
            "of modules that appear in the graph; never invent modules.\n"
            "- A layer is a set of modules with a shared architectural role "
            "(e.g. a 'services' layer, an 'agents/LLM' layer). Give each a short "
            "name, a one-line responsibility, and the modules it contains.\n"
            "- Note the overall dependency direction the edges imply (which "
            "layers depend on which).\n\n"
            "Return ONLY JSON:\n"
            "{\n"
            '  "layers": [\n'
            '    {"name": "<layer>", "responsibility": "<one line>", '
            '"modules": ["<module name from the graph>"],\n'
            '     "depends_on": ["<layer this layer depends on>"]}\n'
            "  ]\n"
            "}"
        )

    def build_user_input(self, payload: ArchitectureInput) -> str:
        return (
            "module dependency graph (JSON, edges are FACTS):\n"
            f"{json.dumps(_graph_for_prompt(payload.dependency_graph), indent=2)}\n\n"
            "per-file roles (JSON):\n"
            f"{json.dumps(_roles_for_prompt(payload.file_roles), indent=2)}"
        )

    def parse_payload(
        self, obj: object, response: DeepSeekResponse
    ) -> ArchitectureStructure:
        if not isinstance(obj, dict) or not isinstance(obj.get("layers"), list):
            raise AgentResponseError(
                'architecture response missing "layers" array',
                raw_content=response.content,
            )
        return ArchitectureStructure(layers=obj["layers"])


# ============================================================================ #
# Rung 3b — architecture PROSE (its own small call)
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class ProseInput:
    """What rung 3b reads: the assembled architecture + the compact role table."""

    architecture: dict  # {"layers", "modules", "dependencies"}
    file_roles: list[dict]


class ArchitectureProseAgent(BaseAgent[ProseInput, str]):
    """Assembled structure in, human-readable prose out (rung 3b).

    Pure narration of an already-decided structure, so thinking is off and the
    budget is modest — this call can't blow up the way the old combined call did.
    """

    name = "map-architecture-prose"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("model", "deepseek-v4-pro")
        kwargs.setdefault("thinking", False)
        kwargs.setdefault("max_tokens", 2048)
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def system_prompt(self) -> str:
        return (
            "You are writing the human-readable overview for a project map. You "
            "are given the codebase's architecture (layers, modules, and the "
            "dependency edges between them) and a table of per-file roles.\n\n"
            "Write a few short paragraphs describing how the codebase fits "
            "together: the layers, the key modules, and how they relate.\n\n"
            "Rules:\n"
            "- Describe only what the inputs show. Do not invent modules or "
            "relationships.\n"
            "- Write for a human reviewer skimming the map — clear and concise, "
            "not a bullet dump.\n\n"
            'Return ONLY JSON: {"prose": "<a few short paragraphs>"}'
        )

    def build_user_input(self, payload: ProseInput) -> str:
        return (
            "architecture (JSON):\n"
            f"{json.dumps(_architecture_for_prompt(payload.architecture), indent=2)}\n\n"
            "per-file roles (JSON):\n"
            f"{json.dumps(_roles_for_prompt(payload.file_roles), indent=2)}"
        )

    def parse_payload(self, obj: object, response: DeepSeekResponse) -> str:
        if not isinstance(obj, dict):
            raise AgentResponseError(
                "prose response was not a JSON object",
                raw_content=response.content,
            )
        return str(obj.get("prose", "")).strip()


# ============================================================================ #
# Rung 4 — candidate invariants (reads the compact structure, not the table)
# ============================================================================ #
@dataclass(frozen=True, slots=True)
class InvariantInput:
    """What rung 4 proposes rules from: the assembled architecture + roles.

    The structured architecture (layers + modules + the dependency graph) gives
    the concrete things a rule attaches to; the compact roles add responsibility
    detail. No per-file imports — the graph already summarises dependencies.
    """

    architecture: dict
    file_roles: list[dict]


class InvariantAgent(BaseAgent[InvariantInput, list[Invariant]]):
    """Architecture in, a small set of *candidate* invariants out (rung 4).

    The output is deliberately unratified: a human approves/edits/rejects each
    one (§7.3) before the drift check may cite it. Strong model + thinking on,
    with output headroom.
    """

    name = "map-invariants"

    def __init__(self, **kwargs: object) -> None:
        kwargs.setdefault("model", "deepseek-v4-pro")
        kwargs.setdefault("thinking", True)
        kwargs.setdefault("max_tokens", 8192)  # was 2048
        kwargs.setdefault("max_token_ceiling", 32768)  # NEW
        super().__init__(**kwargs)  # type: ignore[arg-type]

    def system_prompt(self) -> str:
        return (
            "You are a staff engineer proposing architectural INVARIANTS for a "
            "codebase — a small set of explicit, checkable rules capturing how "
            "the code is meant to fit together. A later automated check cites "
            "these by name against incoming changes, so each must be concrete "
            "enough to test a diff against.\n\n"
            "You are given the codebase's architecture (layers, modules, and the "
            "dependency edges between them) plus per-file roles.\n\n"
            "Good invariants: layering/dependency rules (\"ui/ may depend on "
            "core/, never the reverse\"), I/O ownership (\"only net/ performs "
            "network I/O\"), per-module responsibility (\"parser/ does "
            "tokens->AST, no I/O\"), naming/ownership conventions.\n\n"
            "Rules:\n"
            "- Propose FEW, STRONG rules (roughly 3-8). A plausible-but-wrong "
            "invariant is worse than none, because it will fail good code.\n"
            "- Ground every rule in the provided architecture. Only reference "
            "modules/layers that appear in the inputs.\n"
            "- Each rule gets a short stable kebab-case id, the rule in one "
            "sentence, and a one-line rationale.\n"
            "- These are CANDIDATES for human review; prefer rules a reviewer can "
            "clearly accept or reject.\n\n"
            "Return ONLY JSON:\n"
            '{"invariants": [{"id": "<kebab-id>", "rule": "<one sentence>", '
            '"rationale": "<why it matters>"}]}'
        )

    def build_user_input(self, payload: InvariantInput) -> str:
        return (
            "architecture (JSON):\n"
            f"{json.dumps(_architecture_for_prompt(payload.architecture), indent=2)}\n\n"
            "per-file roles (JSON):\n"
            f"{json.dumps(_roles_for_prompt(payload.file_roles), indent=2)}"
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