"""
/api/projects — connecting and managing tracked repositories (Design §4.1).

Connecting a project clones a *public* GitHub repo locally and records it. No
GitHub credentials, no write access, no app install — the tool only ever reads
a local clone.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import config
from ..models import MAP_NOT_BUILT, Project, ProjectCreate
from ..services import git_service, map_service
from ..storage import store
from .common import get_record_or_404, name_from_url, new_project_id, to_public

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[Project])
def list_projects() -> list[Project]:
    """All tracked projects."""
    return [to_public(record) for record in store.list()]


@router.post("", response_model=Project, status_code=201)
def add_project(payload: ProjectCreate) -> Project:
    """
    Connect a new project: clone the repo, detect its default branch, and record it.

    Cloning is deterministic; any failure (bad URL, private repo, network) is
    surfaced verbatim as a 400 so the user can act on it.
    """
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="A repository URL is required.")

    project_id = new_project_id()
    repo_path = config.REPOS_DIR / project_id

    try:
        git_service.clone_repo(url, repo_path)
        default_branch = git_service.detect_default_branch(repo_path)
    except git_service.GitError as exc:
        # Clean up a partial clone so we don't leave orphans behind.
        if repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Couldn't connect repository: {exc}")

    record = {
        "id": project_id,
        "name": payload.name or name_from_url(url),
        "url": url,
        "default_branch": default_branch,
        "map_status": MAP_NOT_BUILT,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_path": str(repo_path),  # internal only
    }
    store.add(record)
    return to_public(record)


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: str) -> Project:
    """A single tracked project."""
    return to_public(get_record_or_404(project_id))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str) -> None:
    """Stop tracking a project and remove its clone and map from disk."""
    record = get_record_or_404(project_id)

    repo_path = record.get("repo_path")
    if repo_path:
        shutil.rmtree(repo_path, ignore_errors=True)
    shutil.rmtree(map_service.map_dir_for(project_id), ignore_errors=True)

    store.delete(project_id)
