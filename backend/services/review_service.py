"""
Review orchestration — Phase B of the design.

This is the seam where a change gets reviewed. Two pieces are real today:

  * ``compare`` — the deterministic three-dot diff of two branches, and
  * ``run_agents`` — the three review agents (§6) fanned out over an evidence
    bundle + project map. The agents themselves are real; their *inputs* (tool
    output and the map) are stubbed for now (see ``backend/agents/stubs.py`` and
    ``run_agents_on_stubs`` below).

The remaining Phase B stages are still stubbed as clearly-named seams so the
full pipeline shape stays visible and callers won't need to change.

Full Phase B pipeline (Design §5, §6, §8), built on top of ``compare``:

    diff ─▶ run_tools()            clang-tidy · cppcheck · clang-format · lizard
                                   on the FULL changed files (§4.2), line-numbered
         ─▶ build_evidence_bundle() partition findings by axis (§5)
         ─▶ run_agents()           three presentation agents, one per axis (§6)  ✅ built
         ─▶ run_drift_check()      diff vs ratified invariants + map; may abstain (§8)
         ─▶ synthesise()           one call → prioritised overview + verdict (§6)

Each stage is "one decision type per LLM call"; the deterministic tools and the
diff feed them ground truth so every finding stays citable.
"""

from __future__ import annotations

from pathlib import Path

from . import git_service
from ..agents import (
    AgentResult,
    DriftFinding,
    EvidenceBundle,
    ProjectMap,
    ReviewInput,
    StepLogger,
    stubs,
)
from ..agents.review_agents import REVIEW_AGENTS


def compare(repo_path: Path, base: str, compare_branch: str) -> dict:
    """Deterministic diff of two branches (the first Phase B step built)."""
    return git_service.diff_branches(repo_path, base, compare_branch)


# --------------------------------------------------------------------------- #
# Review agents (§6) — real agents, currently fed stubbed inputs.
# --------------------------------------------------------------------------- #
# Drift routes only into the Structure and Maintainability axes (Design §8);
# Readability never receives drift.
_DRIFT_ROUTING: dict[str, bool] = {
    "readability": False,
    "structure": True,
    "maintainability": True,
}


def run_agents(
    evidence: EvidenceBundle,
    project_map: ProjectMap,
    drift: list[DriftFinding] | None = None,
    *,
    logger: StepLogger | None = None,
    **agent_kwargs: object,
) -> dict[str, AgentResult]:
    """
    Run the three review agents over their partitioned evidence (§6).

    Each agent sees only its own axis slice of ``evidence`` plus the shared
    ``project_map``; drift is routed to Structure and Maintainability only (§8).
    ``agent_kwargs`` (e.g. ``model=``, ``api_key=``, ``thinking=``) are passed
    through to each agent's constructor.

    Returns a dict keyed by axis: ``{"readability": AgentResult, ...}``.

    Note: this issues one DeepSeek call per agent, so it requires a configured
    ``DEEPSEEK_API_KEY`` (or an explicit ``api_key=``). The inputs are stubbed;
    the model calls are not.
    """
    drift = drift or []
    results: dict[str, AgentResult] = {}

    for axis, agent_cls in REVIEW_AGENTS.items():
        agent = agent_cls(logger=logger, **agent_kwargs)  # type: ignore[arg-type]
        payload = ReviewInput(
            axis=axis,
            findings=evidence.for_axis(axis),
            project_map=project_map,
            drift=drift if _DRIFT_ROUTING[axis] else [],
        )
        results[axis] = agent.run(payload)

    return results


def run_agents_on_stubs(
    *,
    logger: StepLogger | None = None,
    **agent_kwargs: object,
) -> dict[str, AgentResult]:
    """
    Convenience: run the three agents against the stubbed evidence/map/drift.

    This is the demo path until the tool layer (§5) and map engine (§7.2) are
    built — it proves the agents end-to-end with representative inputs. Swap the
    stub producers for the real ones and the agents are unchanged.
    """
    return run_agents(
        stubs.stub_evidence_bundle(),
        stubs.stub_project_map(),
        stubs.stub_drift_findings(),
        logger=logger,
        **agent_kwargs,
    )


# --------------------------------------------------------------------------- #
# Not yet implemented — the remaining Phase B seams. Kept explicit so the shape
# of the pipeline is visible and callers won't need to change.
# --------------------------------------------------------------------------- #
def run_tools(repo_path: Path, changed_files: list[dict]) -> dict:
    """Run the deterministic analysers on the full changed files (Design §5)."""
    raise NotImplementedError("Phase B tool layer not yet implemented (Design §5).")


def build_evidence_bundle(tool_findings: dict) -> EvidenceBundle:
    """Partition tool findings by axis so the agents can't overlap (Design §5)."""
    raise NotImplementedError("Evidence partitioning not yet implemented (Design §5).")


def run_drift_check(diff: str, project_map: ProjectMap) -> list[DriftFinding]:
    """Check the diff against ratified invariants; may abstain (Design §8)."""
    raise NotImplementedError("Drift check not yet implemented (Design §8).")


def synthesise(
    agent_results: dict[str, AgentResult],
    drift: list[DriftFinding],
) -> dict:
    """One call → prioritised overview + overall verdict (Design §6)."""
    raise NotImplementedError("Synthesis step not yet implemented (Design §6).")