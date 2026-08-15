# Smart Code Reviewer

An AI pre-review assistant for C++ that runs *before* a human opens a pull
request. This repository is the **shell**: the deterministic plumbing and the UI
are in place, and the intelligence layer (the map engine and the review agents)
slots into clearly-marked seams.

See `Design Document.md` for the full design.

---

## What works today vs. what's stubbed

| Capability | Status | Where |
|---|---|---|
| Connect a public GitHub repo (clone locally) | ✅ real | `services/git_service.py` |
| List branches, detect default branch | ✅ real | `services/git_service.py` |
| Three-dot diff (`git diff base...compare`) | ✅ real | `services/git_service.py` · `review_service.compare` |
| Three-page UI (Connect → Map → Review) | ✅ real | `frontend/` |
| Build the project map | 🟡 **stub** — writes an empty scaffold | `services/map_service.build_map` |
| Tools → agents → drift → synthesis (Phase B) | ⬜ not built — seams in place | `services/review_service.py` |

Everything *deterministic* (clone, branches, diff) is real. Only the parts that
need the LLM/analysers are stubbed, so the app is fully clickable end to end.

---

## Quick start

Requires Python 3.10+ and `git` on your PATH.

```bash
cd smart-code-reviewer
python -m venv .venv && source .venv/bin/activate    # optional
pip install -r requirements.txt
python run.py                                         # or: uvicorn backend.main:app --reload
```

Open **http://127.0.0.1:8000**.

1. **Connect** — paste a public GitHub URL (e.g. `https://github.com/owner/repo`).
   It's cloned into `data/repos/<id>/` (read-only use, no credentials).
2. **Map** — click *Build map*. Currently writes an empty scaffold to
   `data/maps/<id>/map.json`.
3. **Review** — pick a base and a compare branch and hit *Compare* to see the
   three-dot diff, changed-file summary, and a line-numbered diff view.

All runtime state lives under `data/` (git-ignored).

---

## Architecture

```
backend/
  main.py                 FastAPI app; mounts /api and serves the frontend
  config.py               filesystem layout (data/, repos/, maps/) + timeouts
  models.py               Pydantic request/response schemas
  storage.py              JSON-backed project registry (swap for a DB later)
  services/
    git_service.py        DETERMINISTIC: clone · branches · three-dot diff
    map_service.py        map scaffold  ← replace with the "climb" (Design §7.2)
    review_service.py     Phase B orchestrator; compare() is real, rest are seams
  routers/
    projects.py           /api/projects            (connect / list / delete)
    maps.py               /api/projects/{id}/map    (build / get)
    review.py             /api/projects/{id}/...    (branches / compare)
frontend/
  index.html · styles.css · client.js · app.js     three-view single page
```

**Design principle carried through the code:** deterministic where possible,
LLM only for judgement. The git layer never guesses; the map and review services
are where model calls will live, each doing one bounded thing.

### Where the remaining work plugs in

- **Map generation** — replace `map_service.build_map`. The scaffold it writes is
  already the target shape (`prose`, `file_roles`, `architecture`, `invariants`),
  so fill it rung by rung per Design §7.2. The API contract and the `map_status`
  transition don't change.
- **Phase B** — flesh out the stubbed methods in `review_service.py`
  (`run_tools` → `build_evidence_bundle` → `run_drift_check` → `synthesise`).
  `compare()` already provides the diff those stages consume.
- **Analysers** — `clang-tidy`, `clang-format`, `cppcheck`, `lizard` are invoked
  from `run_tools`; see the commented dependencies in `requirements.txt`.
