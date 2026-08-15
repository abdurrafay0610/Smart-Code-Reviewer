"""
Project map service — Phase A of the design.

The map is the codebase context file (Design §7): prose describing how the code
fits together, plus a small set of *candidate* architectural invariants for a
human to ratify (§7.3), which the drift check (§8) later cites against.

``build_map`` runs the "climb" (§7.2): a layered pipeline where each rung
consumes the *verified* output of the one below, so errors can't silently
compound and a wrong result is traceable to the rung that produced it.
Deterministic rungs do as much as possible; the model is invoked only for
genuine judgement, one bounded decision per call.

    rung 1  file_tree      git ls-files                         deterministic
    rung 2a file_index     language + imports (source_scan)     deterministic
    rung 2b file_roles     per-file responsibility              LLM, 1 call/file
    rung 3  architecture   layers/modules/deps + prose          LLM, 1 synthesis
    rung 4  invariants     candidate rules (ratified: false)    LLM, 1 call

Each rung is also persisted as its own artifact under ``data/maps/<id>/`` (so
the climb is inspectable and a single rung is re-runnable), and the whole thing
is assembled into ``map.json`` in the shape ``ProjectMap.from_dict`` expects —
so the drift check and the map viewer read one file and don't care that it was
built in stages.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from ..agents.deepseek_client import StepLogger
from ..agents.map_agents import (
    ArchitectureAgent,
    ArchitectureInput,
    InvariantAgent,
    InvariantInput,
    ResponsibilityAgent,
    ResponsibilityInput,
)
from . import git_service, source_scan


def map_dir_for(project_id: str) -> Path:
    return config.MAPS_DIR / project_id


def map_path_for(project_id: str) -> Path:
    return map_dir_for(project_id) / "map.json"


def _empty_scaffold(project_id: str) -> dict:
    """The canonical map shape. Real fields are filled by the climb."""
    return {
        "project_id": project_id,
        "status": "stub",  # -> "built" once the climb runs; "ratified" after §7.3
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


def _write_artifact(out_dir: Path, name: str, payload: dict) -> None:
    """Persist one rung's output so the climb is inspectable and re-runnable."""
    (out_dir / name).write_text(json.dumps(payload, indent=2))


def build_map(
    project: dict,
    *,
    logger: StepLogger | None = None,
    **agent_kwargs: object,
) -> dict:
    """Run the climb for ``project`` and write both the per-rung artifacts and
    the assembled ``map.json``. Returns the assembled map.

    ``project`` is the full storage record (it carries ``repo_path``).
    ``agent_kwargs`` (e.g. ``api_key=``, ``model=``, ``thinking=``) are forwarded
    to every rung's agent; omit them and each rung uses its own sensible default
    (see ``map_agents``). This issues one model call per source file plus two,
    so it requires a configured ``DEEPSEEK_API_KEY`` (or an explicit key).
    """
    project_id = project["id"]
    repo = Path(project["repo_path"])
    out_dir = map_dir_for(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- rung 1: file tree (deterministic) --------------------------------- #
    file_tree = git_service.list_files(repo)
    _write_artifact(out_dir, "01_file_tree.json", {"file_tree": file_tree})

    # -- rung 2a: language + imports (deterministic) ----------------------- #
    file_index = source_scan.scan_files(repo, file_tree)
    _write_artifact(out_dir, "02_file_index.json", {"file_index": file_index})

    # -- rung 2b: per-file responsibility (LLM, one call per file) --------- #
    responsibility_agent = ResponsibilityAgent(logger=logger, **agent_kwargs)  # type: ignore[arg-type]
    file_roles: list[dict] = []
    for entry in file_index:
        source = (repo / entry["path"]).read_text(encoding="utf-8", errors="replace")
        role = responsibility_agent.run(
            ResponsibilityInput(
                path=entry["path"],
                language=entry["language"],
                source=source,
                imports=entry["imports"],
            )
        )
        # path/language/imports are ours (deterministic); only the responsibility
        # comes from the model — re-attach the verified facts here.
        file_roles.append(
            {
                "path": entry["path"],
                "language": entry["language"],
                "imports": entry["imports"],
                "responsibility": role.responsibility,
            }
        )
    _write_artifact(out_dir, "03_file_roles.json", {"file_roles": file_roles})

    # -- rung 3: architecture inference (LLM, the one synthesis call) ------- #
    architecture_agent = ArchitectureAgent(logger=logger, **agent_kwargs)  # type: ignore[arg-type]
    arch = architecture_agent.run(ArchitectureInput(file_roles=file_roles))
    _write_artifact(
        out_dir,
        "04_architecture.json",
        {"prose": arch.prose, "architecture": arch.architecture},
    )

    # -- rung 4: candidate invariants (LLM) -------------------------------- #
    invariant_agent = InvariantAgent(logger=logger, **agent_kwargs)  # type: ignore[arg-type]
    candidates = invariant_agent.run(
        InvariantInput(
            prose=arch.prose,
            architecture=arch.architecture,
            file_roles=file_roles,
        )
    )
    invariants = [
        {"id": c.id, "rule": c.rule, "rationale": c.rationale, "ratified": c.ratified}
        for c in candidates
    ]
    _write_artifact(out_dir, "05_candidate_invariants.json", {"invariants": invariants})

    # -- assemble the final map.json (the shape ProjectMap.from_dict reads) - #
    result = _empty_scaffold(project_id)
    result.update(
        {
            "status": "built",  # invariants are candidates until §7.3 ratifies them
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "prose": arch.prose,
            "file_tree": file_tree,
            "file_roles": file_roles,
            "architecture": arch.architecture,
            "invariants": invariants,
        }
    )
    map_path_for(project_id).write_text(json.dumps(result, indent=2))
    return result