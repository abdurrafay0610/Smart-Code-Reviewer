"""
Project registry — the source of truth for which repositories are tracked.

Backed by a single JSON file (``data/registry.json``) so it is trivially
inspectable and needs no setup. The interface is deliberately DB-shaped
(``list`` / ``get`` / ``add`` / ``update`` / ``delete``) so it can be swapped
for SQLite or Postgres later without touching the routers.

A stored record is a plain dict and may carry internal-only keys the API never
returns:

    {
      "id": "…",              # opaque unique id
      "name": "…",            # display name
      "url": "…",             # origin URL we cloned from
      "default_branch": "…",  # e.g. "main" (detected at connect time)
      "map_status": "…",      # not_built | building | built
      "created_at": "…",      # ISO-8601 UTC
      "repo_path": "…"        # INTERNAL: on-disk clone location
    }
"""

from __future__ import annotations

import json
import threading
from typing import Optional

from . import config


class ProjectStore:
    """Thread-safe JSON-backed store of project records."""

    def __init__(self, path=config.REGISTRY_FILE) -> None:
        self._path = path
        self._lock = threading.Lock()
        if not self._path.exists():
            self._write_all([])

    # -- internal file I/O ------------------------------------------------
    def _read_all(self) -> list[dict]:
        try:
            return json.loads(self._path.read_text() or "[]")
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _write_all(self, records: list[dict]) -> None:
        self._path.write_text(json.dumps(records, indent=2))

    # -- public API -------------------------------------------------------
    def list(self) -> list[dict]:
        with self._lock:
            return self._read_all()

    def get(self, project_id: str) -> Optional[dict]:
        with self._lock:
            for record in self._read_all():
                if record.get("id") == project_id:
                    return record
        return None

    def add(self, record: dict) -> dict:
        with self._lock:
            records = self._read_all()
            records.append(record)
            self._write_all(records)
            return record

    def update(self, project_id: str, **fields) -> Optional[dict]:
        with self._lock:
            records = self._read_all()
            updated = None
            for record in records:
                if record.get("id") == project_id:
                    record.update(fields)
                    updated = record
                    break
            if updated is not None:
                self._write_all(records)
            return updated

    def delete(self, project_id: str) -> bool:
        with self._lock:
            records = self._read_all()
            remaining = [r for r in records if r.get("id") != project_id]
            if len(remaining) == len(records):
                return False
            self._write_all(remaining)
            return True


# A single shared instance is sufficient for this local, single-user tool.
store = ProjectStore()
