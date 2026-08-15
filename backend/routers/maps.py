"""
/api/projects/{id}/map — building and viewing the project map (Design §7).

``build`` is currently a stub (writes an empty scaffold). The endpoint contract
here is the real one, so wiring the actual "climb" later needs no API change.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from ..models import MAP_BUILDING, MAP_BUILT, MAP_NOT_BUILT

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
    record = get_record_or_404(project_id)
    store.update(project_id, map_status=MAP_BUILDING)
    try:
        project_map = map_service.build_map(record)
    except Exception as exc:
        store.update(project_id, map_status=MAP_NOT_BUILT)
        raise HTTPException(status_code=502, detail=f"Map build failed: {exc}")
    store.update(project_id, map_status=MAP_BUILT)
    return {"status": "built", "map": project_map}
