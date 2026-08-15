"""
Central configuration: filesystem layout and runtime settings.

Everything the app writes at runtime lives under ``data/`` at the project root:

    data/
      registry.json     # the list of tracked projects (see storage.py)
      repos/<id>/       # a full clone of each connected repository
      maps/<id>/        # the generated project map for each repository

``data/`` is created on import and is git-ignored — it is pure runtime state.
"""

from pathlib import Path

# Project root = the directory that contains both ``backend/`` and ``frontend/``.
BASE_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = BASE_DIR / "frontend"

DATA_DIR = BASE_DIR / "data"
REPOS_DIR = DATA_DIR / "repos"
MAPS_DIR = DATA_DIR / "maps"
REGISTRY_FILE = DATA_DIR / "registry.json"
BIN_DIR = BASE_DIR / "bin"

# Guard rails for the deterministic git layer.
GIT_CLONE_TIMEOUT = 300  # seconds; large repos take a while to clone
GIT_COMMAND_TIMEOUT = 120  # seconds; per non-clone git invocation

# Create the runtime directories on import so nothing downstream has to worry
# about their existence.
for _directory in (DATA_DIR, REPOS_DIR, MAPS_DIR):
    _directory.mkdir(parents=True, exist_ok=True)
