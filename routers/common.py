"""Helpers shared across routers: id/name derivation, lookups, and view mapping."""

from __future__ import annotations

import re
import uuid

from fastapi import HTTPException

from ..models import Project
from ..storage import store


def new_project_id() -> str:
    """Opaque, collision-resistant id."""
    return uuid.uuid4().hex[:12]


def name_from_url(url: str) -> str:
    """Derive a friendly display name from a repo URL (last path segment, no .git)."""
    cleaned = url.strip().rstrip("/")
    tail = cleaned.split("/")[-1] if "/" in cleaned else cleaned
    tail = re.sub(r"\.git$", "", tail)
    return tail or "project"


def get_record_or_404(project_id: str) -> dict:
    """Fetch a stored project record or raise a 404."""
    record = store.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return record


def to_public(record: dict) -> Project:
    """Convert an internal storage record into the public Project model."""
    return Project(
        id=record["id"],
        name=record["name"],
        url=record["url"],
        default_branch=record.get("default_branch"),
        map_status=record.get("map_status", "not_built"),
        created_at=record["created_at"],
    )
