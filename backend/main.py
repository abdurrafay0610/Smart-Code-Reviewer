"""
Application entrypoint.

Wires the API routers under ``/api`` and serves the static frontend at ``/``.
Run it with::

    uvicorn backend.main:app --reload      # or: python run.py

then open http://127.0.0.1:8000.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .routers import maps, projects, review

app = FastAPI(title="Smart Code Reviewer", version="0.1.0")

# Permissive CORS: this is a local, single-user tool. Tighten if ever hosted.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "version": app.version}


# Order matters: specific /api routes are registered before the catch-all static
# mount, so API calls are never shadowed by the frontend.
app.include_router(projects.router, prefix="/api")
app.include_router(maps.router, prefix="/api")
app.include_router(review.router, prefix="/api")

# Serve the SPA. ``html=True`` returns index.html at "/" and resolves static assets.
app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True), name="frontend")
