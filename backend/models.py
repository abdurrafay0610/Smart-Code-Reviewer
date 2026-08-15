"""
API schemas (Pydantic models).

These describe the shapes that cross the HTTP boundary. Internal storage records
(see ``storage.py``) may carry extra fields (e.g. on-disk paths) that we choose
not to expose; the routers translate those records into the public models below.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Map lifecycle states. Kept as plain strings for now; the real engine (Design
# §7.2) will move through NOT_BUILT -> BUILDING -> BUILT and may add RATIFIED.
MAP_NOT_BUILT = "not_built"
MAP_BUILDING = "building"
MAP_BUILT = "built"


class ProjectCreate(BaseModel):
    """Payload for connecting a new project."""

    url: str = Field(..., description="Public GitHub repository URL to clone.")
    name: Optional[str] = Field(
        default=None,
        description="Optional display name. Derived from the URL when omitted.",
    )


class Project(BaseModel):
    """Public view of a tracked project."""

    id: str
    name: str
    url: str
    default_branch: Optional[str] = None
    map_status: str = MAP_NOT_BUILT
    created_at: str


class BranchList(BaseModel):
    """Branches available on a connected project."""

    branches: list[str]
    default_branch: Optional[str] = None


class CompareRequest(BaseModel):
    """Payload for comparing two branches."""

    base: str = Field(..., description="Base branch — the established side (e.g. main).")
    compare: str = Field(..., description="Compare branch — the proposed change (e.g. a feature branch).")


class ChangedFile(BaseModel):
    """One file touched by a diff."""

    path: str
    status: str  # A (added) | M (modified) | D (deleted) | R (renamed) | C (copied)
    old_path: Optional[str] = None  # populated for renames/copies
    additions: Optional[int] = None  # None for binary files
    deletions: Optional[int] = None


class DiffStats(BaseModel):
    files_changed: int
    additions: int
    deletions: int


class CompareResult(BaseModel):
    """Result of a three-dot ``base...compare`` diff."""

    base: str
    compare: str
    merge_base: Optional[str] = None
    stats: DiffStats
    changed_files: list[ChangedFile]
    diff: str  # the raw unified patch, rendered client-side
