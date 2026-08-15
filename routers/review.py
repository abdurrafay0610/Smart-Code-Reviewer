"""
/api/projects/{id}/... — branch discovery and the branch comparison (Design §4.2).

The comparison is the entry point to Phase B. Today it returns the deterministic
three-dot diff; later the same request will additionally carry the analysed
findings (tools → agents → drift → synthesis).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..models import BranchList, CompareRequest, CompareResult
from ..services import git_service, review_service
from .common import get_record_or_404

router = APIRouter(prefix="/projects/{project_id}", tags=["review"])


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
