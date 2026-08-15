"""
/api/projects/{id}/...  -  branch discovery, comparison, and the AI review (Design 4.2, 5, 6).

``/compare`` is the deterministic entry to Phase B: the three-dot diff. ``/review``
runs the full pipeline on top of it  -  deterministic tools -> evidence bundle -> the
three per-axis agents (Design 5, 6)  -  and returns their interpreted findings.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..agents import AgentResult, ProjectMap
from ..models import (
    AxisReview,
    BranchList,
    CompareRequest,
    CompareResult,
    ReviewFinding,
    ReviewResult,
)
from ..services import git_service, map_service, review_service
from .common import get_record_or_404

router = APIRouter(prefix="/projects/{project_id}", tags=["review"])

#: Fixed presentation order for the review tabs (Design 9).
_AXIS_ORDER = ("readability", "structure", "maintainability")

#: The reference adapter's language (Design 5, 10). run_review defaults to this;
#: kept here so the response can echo it back to the UI.
_LANGUAGE = "Python"


def _repo_path(record: dict) -> Path:
    repo_path = record.get("repo_path")
    if not repo_path or not Path(repo_path).exists():
        raise HTTPException(
            status_code=409,
            detail="The local clone for this project is missing. Reconnect the project.",
        )
    return Path(repo_path)


@router.get("/branches", response_model=BranchList)
def list_branches(project_id: str) -> BranchList:
    """Branches available to compare, plus the detected default (pre-selected as base)."""
    record = get_record_or_404(project_id)
    repo_path = _repo_path(record)
    try:
        branches = git_service.list_branches(repo_path)
    except git_service.GitError as exc:
        raise HTTPException(status_code=500, detail=f"Couldn't list branches: {exc}")
    return BranchList(branches=branches, default_branch=record.get("default_branch"))


@router.post("/compare", response_model=CompareResult)
def compare_branches(project_id: str, payload: CompareRequest) -> CompareResult:
    """Three-dot diff of ``compare`` against ``base`` (``git diff base...compare``)."""
    record = get_record_or_404(project_id)
    repo_path = _repo_path(record)

    if payload.base == payload.compare:
        raise HTTPException(status_code=400, detail="Choose two different branches to compare.")

    try:
        result = review_service.compare(repo_path, payload.base, payload.compare)
    except git_service.GitError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't compare branches: {exc}")

    return CompareResult(**result)


@router.post("/review", response_model=ReviewResult)
def review_changes(project_id: str, payload: CompareRequest) -> ReviewResult:
    """
    Run the full review pipeline for ``base...compare`` and return per-axis findings.

    Pipeline (Design 5, 6): diff -> deterministic tools -> evidence bundle -> three
    agents. This issues one model call per axis, so it needs ``DEEPSEEK_API_KEY`` set.
    The project map is loaded if present; an unbuilt map simply means the agents run
    without architectural context (drift is not wired yet).
    """
    record = get_record_or_404(project_id)
    repo_path = _repo_path(record)

    if payload.base == payload.compare:
        raise HTTPException(status_code=400, detail="Choose two different branches to compare.")

    project_map = ProjectMap.from_dict(map_service.get_map(project_id))

    try:
        results = review_service.run_review(
            repo_path,
            payload.base,
            payload.compare,
            project_map,
            language=_LANGUAGE,
        )
    except git_service.GitError as exc:
        raise HTTPException(status_code=400, detail=f"Couldn't compare branches: {exc}")
    except Exception as exc:  # agent/provider failures (missing key, bad response, ...)
        raise HTTPException(status_code=502, detail=f"The review agents failed: {exc}")

    return _serialise_review(payload.base, payload.compare, results)


def _serialise_review(
    base: str, compare: str, results: dict[str, AgentResult]
) -> ReviewResult:
    """Turn the ``{axis: AgentResult}`` map into the API's ReviewResult shape."""
    axes: list[AxisReview] = []
    finding_count = 0
    total_tokens = 0

    for axis in _AXIS_ORDER:
        result = results.get(axis)
        if result is None:
            continue
        findings = [
            ReviewFinding(
                title=f.title,
                detail=f.detail,
                severity=f.severity,
                citations=list(f.citations),
                suggestion=f.suggestion,
            )
            for f in result.findings
        ]
        finding_count += len(findings)
        total_tokens += result.total_tokens or 0
        axes.append(
            AxisReview(
                axis=result.axis,
                summary=result.summary,
                abstained=result.abstained,
                findings=findings,
                model=result.model,
                total_tokens=result.total_tokens,
            )
        )

    return ReviewResult(
        base=base,
        compare=compare,
        language=_LANGUAGE,
        axes=axes,
        finding_count=finding_count,
        total_tokens=total_tokens,
    )