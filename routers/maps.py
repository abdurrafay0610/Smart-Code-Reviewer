"""
/api/projects/{id}/map — building and viewing the project map (Design §7).

``build`` is currently a stub (writes an empty scaffold). The endpoint contract
here is the real one, so wiring the actual "climb" later needs no API change.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..models import MAP_BUILT
from ..services import map_service
from ..storage import store
from .common import get_record_or_404

router = APIRouter(prefix="/projects/{project_id}/map", tags=["map"])


@router.get("")
def get_map(project_id: str) -> dict:
    """Return the stored map, or a not-built marker if it hasn't been generated."""
    get_record_or_404(project_id)  # 404 if the project is unknown
    project_map = map_service.get_map(project_id)
    if project_map is None:
        return {"status": "not_built", "map": None}
    return {"status": project_map.get("status", "built"), "map": project_map}


@router.post("")
def build_map(project_id: str) -> dict:
    """
    Build (currently: scaffold) the project map and mark the project as built.

    Replace ``map_service.build_map`` with the real engine (Design §7.2) — this
    endpoint and the stored ``map_status`` transition stay the same.
    """
    record = get_record_or_404(project_id)
    project_map = map_service.build_map(record)
    store.update(project_id, map_status=MAP_BUILT)
    return {"status": "built", "map": project_map}
