"""
Review orchestration — Phase B of the design.

This is the seam where a change gets reviewed. Today it does the one
deterministic thing the shell needs: compute the three-dot diff of two branches.
The remaining Phase B stages are stubbed as clearly-named methods so the full
pipeline can be filled in without changing this module's callers.

Full Phase B pipeline (Design §5, §6, §8), to be built on top of ``compare``:

    diff ─▶ run_tools()            clang-tidy · cppcheck · clang-format · lizard
                                   on the FULL changed files (§4.2), line-numbered
         ─▶ build_evidence_bundle() partition findings by axis so agents can't
                                    overlap (§5)  →  {readability, structure, maint}
         ─▶ run_agents()           three presentation agents, one per axis (§6)
         ─▶ run_drift_check()      diff vs ratified invariants + map; may abstain (§8)
         ─▶ synthesise()           one call → prioritised overview + verdict (§6)

Each stage is "one decision type per LLM call"; the deterministic tools and the
diff feed them ground truth so every finding stays citable.
"""

from __future__ import annotations

from pathlib import Path

from . import git_service


def compare(repo_path: Path, base: str, compare_branch: str) -> dict:
    """Deterministic diff of two branches (the only Phase B step built so far)."""
    return git_service.diff_branches(repo_path, base, compare_branch)


# --------------------------------------------------------------------------- #
# Not yet implemented — the intelligence layer. Kept as explicit seams so the
# shape of the pipeline is visible and callers won't need to change.
# --------------------------------------------------------------------------- #
def run_tools(repo_path: Path, changed_files: list[dict]) -> dict:
    """Run the deterministic analysers on the full changed files (Design §5)."""
    raise NotImplementedError("Phase B tool layer not yet implemented (Design §5).")


def build_evidence_bundle(tool_findings: dict) -> dict:
    """Partition tool findings by axis so the agents can't overlap (Design §5)."""
    raise NotImplementedError("Evidence partitioning not yet implemented (Design §5).")


def run_drift_check(diff: str, project_map: dict) -> dict:
    """Check the diff against ratified invariants; may abstain (Design §8)."""
    raise NotImplementedError("Drift check not yet implemented (Design §8).")


def synthesise(evidence: dict, drift: dict) -> dict:
    """One call → prioritised overview + overall verdict (Design §6)."""
    raise NotImplementedError("Synthesis step not yet implemented (Design §6).")
