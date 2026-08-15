"""
Project map service.

The map is the codebase context file (Design §7) — prose describing each
module's responsibility plus a small set of ratified, checkable *invariants*
that the drift check (Design §8) cites against.

>>> CURRENT STATE: STUB <<<
``build_map`` writes an empty scaffold to disk and nothing more. The scaffold's
*shape* is the real target shape, so replacing the stub with the real engine is
a matter of populating fields, not restructuring callers.

To replace the stub (Design §7.2 — "the climb"), fill the scaffold rung by rung,
each rung consuming the verified output of the one below:

    1. file_tree     ← git ls-files / directory walk          (deterministic)
    2. file_roles[]  ← per-file language + imports             (deterministic)
                     ← per-file responsibility                 (LLM, one file/batch)
    3. architecture  ← infer layers/modules from the role table (LLM, one synthesis call)
    4. invariants[]  ← propose candidate rules                 (LLM)
                     ← human ratifies approve/edit/reject (§7.3)

Only steps that need genuine judgement call the model; the rest is code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config


def map_dir_for(project_id: str) -> Path:
    return config.MAPS_DIR / project_id


def map_path_for(project_id: str) -> Path:
    return map_dir_for(project_id) / "map.json"


def _empty_scaffold(project_id: str) -> dict:
    """The canonical (empty) map shape. Real fields are filled by the climb."""
    return {
        "project_id": project_id,
        "status": "stub",  # -> "built" / "ratified" once the real engine lands
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prose": "",  # human-readable module descriptions (§7.1)
        "file_tree": [],  # deterministic (rung 1)
        "file_roles": [],  # [{path, language, imports, responsibility}] (rung 2)
        "architecture": {},  # layers/modules and their relationships (rung 3)
        "invariants": [],  # [{id, rule, rationale, ratified}] (rung 4 + §7.3)
    }


def get_map(project_id: str) -> dict | None:
    """Return the stored map for a project, or None if it has not been built."""
    path = map_path_for(project_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def build_map(project: dict) -> dict:
    """
    STUB: create an empty map scaffold on disk for ``project`` and return it.

    ``project`` is the full storage record (so the future real implementation
    has ``repo_path`` etc. available); the stub only needs the id.
    """
    project_id = project["id"]
    path = map_path_for(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    scaffold = _empty_scaffold(project_id)
    path.write_text(json.dumps(scaffold, indent=2))
    return scaffold
