# Smart Code Reviewer

An AI pre-review assistant that runs *before* a human opens a pull request. It
reviews a proposed change on three axes — **readability, structure, and
maintainability** — and is designed to additionally catch **architectural
drift**: code that is locally clean but doesn't fit the established shape of the
codebase.

The differentiator is not "we called an LLM." It's *how* the model is used:
**every judgement is grounded in something external** — either a deterministic
static-analysis finding (with a line number) or a ratified architectural
invariant (with a rule name). The model interprets, prioritises, and explains
that evidence like a senior reviewer; it never hunts for issues from a blank
slate. Because the citations are visible in the output, the rigour is something
the reviewer can *see*.

> **Read the design first.** [`Design Document.md`](./Design%20Document.md) is
> the authoritative technical design — the architecture, the two-phase flow, the
> evidence/axis routing, the map "climb," drift detection, and the scope
> decisions. This README covers what's in the code today and how to run it.

**Language.** The architecture is language-neutral — everything the model touches
consumes *findings*, not source. The single language-dependent component is the
deterministic tool layer, which is a pluggable adapter. This reference
implementation targets **Python**, chosen so the reviewer can be pointed at its
own codebase (it dogfoods itself). The originally-scoped language, C++, is
supported by the same architecture with a different adapter (clang-tidy,
cppcheck, clang-format, lizard) — the signal set, axis partition, and thresholds
are identical; only the producing tools change.

---

## Status: what's built vs. what's designed

Everything **deterministic** (clone, branches, diff, the tool layer, the map's
non-LLM rungs) runs without an API key. Everything that needs *judgement* is a
bounded DeepSeek call funnelled through one client.

| Capability | Status | Where |
|---|---|---|
| Connect a public GitHub repo (clone locally, read-only) | ✅ built | `services/git_service.py` · `routers/projects.py` |
| List branches, detect default branch | ✅ built | `services/git_service.py` · `routers/review.py` |
| Three-dot diff (`git diff base...compare`) | ✅ built | `services/git_service.py` · `review_service.compare` |
| **Project map — the full "climb" (Design §7.2)** | ✅ built | `services/map_service.py` · `agents/map_agents.py` |
| ├ file tree · language + imports · dependency graph | ✅ built (deterministic) | `git_service` · `source_scan.py` · `module_graph.py` |
| └ per-file responsibility · layers · prose · candidate invariants | ✅ built (LLM rungs) | `agents/map_agents.py` |
| **Deterministic tool layer (Python adapter, Design §5)** | ✅ built | `backend/tools/` |
| └ Ruff · lizard · radon · duplication → evidence bundle | ✅ built | `ruff_tool` · `lizard_tool` · `radon_tool` · `dup_tool` |
| **Three review agents (Design §6)** | ✅ built | `agents/review_agents.py` · `agents/base.py` |
| **Full review pipeline** (diff → tools → evidence → agents) | ✅ built | `review_service.run_review` · `POST /review` |
| Single-page UI (connect · map · diff · review tabs) | ✅ built | `frontend/` |
| Self-review / dogfood script | ✅ built | `scripts/analyze_path.py` |
| **Drift detection** (diff vs ratified invariants, Design §8) | 🟡 seam | `review_service.run_drift_check` — `NotImplementedError` |
| **Synthesis / Overview verdict** (Design §6) | 🟡 seam | `review_service.synthesise` — `NotImplementedError` |
| Invariant **ratification** UI (Design §7.3) | 🟡 by hand | map emits candidates (`ratified: false`) |
| Map **auto-update** loop (post-merge hook / CI, Design §10) | ⬜ narrated | driven manually in the demo |

The demo path — **connect → build map → compare branches → run AI review** — is
real end to end. The two remaining 🟡 items are the drift check and the overview
synthesiser: both are specified in the design and present in the code as
clearly-named seams, ready to fill without changing any API contract or caller.

---

## How it works (in brief)

Two phases. See the design document for the full flow (including a diagram).

**Phase A — build the map, once, when a project is connected.** A layered
"climb" where each rung consumes the *verified* output of the one below, so
errors can't silently compound and a wrong result is traceable to the rung that
produced it:

```
git ls-files ─▶ language + imports ─▶ per-file responsibility (LLM) ─▶
module dependency graph ─▶ layers (LLM) ─▶ prose (LLM) ─▶ candidate invariants (LLM)
```

Deterministic steps do as much as possible; the model is invoked only for
judgement, one bounded decision per call. Each rung is written as its own
artifact under `data/maps/<id>/`, then assembled into `map.json`.

**Phase B — review a change, on branch selection.** The change is the three-dot
diff of a compare branch against a base (what the feature branch introduced since
it forked). Deterministic tools run on the **full changed files**, their findings
are partitioned by axis into an evidence bundle, and the three agents interpret
their own slice (plus the map) into reviewer-style findings:

```
base...compare diff ─▶ Ruff · lizard · radon · duplication ─▶
evidence bundle (partitioned by axis) ─▶ Readability · Structure · Maintainability agents
```

Drift findings (once wired) route into the Structure and Maintainability tabs;
the synthesiser (once wired) produces the prioritised Overview verdict.

**Three principles hold it together (Design §2):**

1. **Deterministic where possible, LLM only for judgement.** File trees,
   language detection, import extraction, the dependency graph, and diffs are
   computed by code — the model is handed ground truth.
2. **One decision type per LLM call.** Every model step makes a single bounded
   judgement against provided evidence.
3. **No claim without a citation.** Every finding points to a line number (from a
   tool) or a named invariant (from the map). This is the hallucination firewall.

---

## Requirements

- **Python 3.10+** and **`git`** on your `PATH`.
- **A DeepSeek API key** for the LLM steps (map building and the review agents).
  The deterministic parts — clone, branches, diff, the file tree, and the tool
  layer — run fine without one.

Python dependencies are pinned in **`requirements.txt`**:

- `fastapi` — the web framework serving the API and the frontend.
- `uvicorn` — the ASGI server (`run.py` / `--reload`).
- `pydantic` — request/response schemas (`backend/models.py`).
- `openai` — used as the DeepSeek client; DeepSeek exposes an OpenAI-compatible
  API, so the SDK is simply pointed at DeepSeek's base URL.
- `lizard` — structural metrics (complexity, length, parameters, nesting).
- `radon` — the composite maintainability index.
- `python-dotenv` *(optional but recommended)* — auto-loads a local `.env` so
  `DEEPSEEK_API_KEY` is picked up without exporting it by hand.

> **Ruff** is *not* a normal pip dependency. It's the one genuine compiled binary
> in the Python adapter, so `setup.py` downloads a standalone build into `./bin`
> (its version stays decoupled from your environment). If a `ruff` is already on
> your `PATH` — e.g. via `pip install ruff` — the tool layer falls back to it.

---

## Setup & run

From the project root:

```bash
# 1. Create and activate a virtualenv (optional but recommended)
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Download the Ruff binary into ./bin  (see note above; skip if ruff is on PATH)
python setup.py

# 4. Configure your environment
cp .env.example .env                 # then edit .env and add your DeepSeek API key

# 5. Run the dev server
python run.py                        # or: uvicorn backend.main:app --reload
```

Then open **http://127.0.0.1:8000**.

`run.py` is a thin launcher (`uvicorn backend.main:app` on `127.0.0.1:8000` with
reload). `setup.py` only places the Ruff binary — it deliberately does **not**
install `requirements.txt`, so run the two in order: `pip install` first, then
`python setup.py`.

All runtime state lives under `data/` (git-ignored): the project registry, one
clone per connected repo (`data/repos/<id>/`), and one map per repo
(`data/maps/<id>/`). Delete `data/` to reset.

---

## Environment (`.env.example`)

Only one variable is required. Copy `.env.example` to `.env` and fill it in:

```dotenv
# Required for every LLM-backed step (the map "climb" and the review agents).
# The deterministic parts of the app (clone, branches, diff, tool layer) do NOT
# need this — you can click through connect/compare without it.
DEEPSEEK_API_KEY=sk-your-key-here

# Optional. Override the DeepSeek endpoint. Defaults to https://api.deepseek.com
# DEEPSEEK_BASE_URL=https://api.deepseek.com

# Optional. Used by setup.py only. Pin a specific Ruff release; otherwise the
# latest release is fetched, falling back to a bundled default version.
# RUFF_VERSION=0.16.3
```

If `python-dotenv` is installed, `.env` is loaded automatically on startup.
Otherwise, export the same variables in your shell before running.

---

## Using it

1. **Connect** — paste a public GitHub URL (e.g. `https://github.com/owner/repo`).
   It's cloned into `data/repos/<id>/` for read-only use (no credentials, no
   write access, no app install).
2. **Map** — click *Build map* to run the climb (this needs `DEEPSEEK_API_KEY`).
   You'll get prose, per-file roles, an inferred architecture, and a small set of
   **candidate** invariants — plus the raw `map.json`. Eyeball the invariants:
   they're proposals for a human to ratify (Design §7.3).
3. **Review** — pick a **base** and a **compare** branch, hit *Compare* to see the
   three-dot diff and changed-file summary, then *Run AI review* to get per-axis
   findings across the **Overview**, **Readability**, **Structure**, and
   **Maintainability** tabs. Findings carry severities, citations, and
   suggestions, and an agent may abstain when its axis is clean.

> **Tip — see it review real code.** Because the reference adapter is Python and
> this backend is Python, the most honest demo points the reviewer at its own
> repository. For a quick, no-server look at just the deterministic evidence:
>
> ```bash
> python scripts/analyze_path.py backend
> ```

---

## Repository layout

```
backend/
  main.py                 FastAPI app; mounts /api and serves the frontend
  config.py               filesystem layout (data/, repos/, maps/, bin/) + git timeouts
  models.py               Pydantic request/response schemas
  storage.py              JSON-backed project registry (swap for a DB later)
  agents/                 the intelligence layer — every model call funnels through here
    deepseek_client.py    the single low-level DeepSeek entry point (query_deepseek)
    base.py               BaseAgent — one bounded model task per instance
    review_agents.py      the three axis agents (readability / structure / maintainability)
    map_agents.py         the map "climb" rungs (responsibility · architecture · prose · invariants)
    types.py              shared dataclasses (findings, evidence bundle, map, invariants, ...)
    stubs.py              representative fixtures for exercising the agents in isolation
  services/
    git_service.py        DETERMINISTIC: clone · branches · three-dot diff · file tree · file-at-rev
    source_scan.py        DETERMINISTIC: per-file language + import extraction (rung 2a)
    module_graph.py       DETERMINISTIC: module dependency graph (rung 2c)
    map_service.py        the climb orchestrator → data/maps/<id>/ + map.json (Phase A)
    review_service.py     Phase B: compare · run_tools · evidence · agents (+ drift/synthesis seams)
  tools/                  the Python adapter — the one language-specific layer
    ruff_tool.py          Ruff: naming, magic numbers, control flow, idioms, warnings, formatting
    lizard_tool.py        lizard: cyclomatic complexity, length, parameters, nesting
    radon_tool.py         radon: composite maintainability index
    dup_tool.py           custom code-duplication check
    routing.py            signal → axis routing (one signal, one home)
    runner.py             run_all_tools + partition_by_axis → the evidence bundle
  routers/
    projects.py           /api/projects                 (connect / list / get / delete)
    maps.py               /api/projects/{id}/map         (build / get)
    review.py             /api/projects/{id}/...         (branches / compare / review)
frontend/
  index.html · styles.css · client.js · app.js          single-page UI
scripts/
  analyze_path.py         run the tool layer on a local path (dogfooding)
setup.py                  download the Ruff binary into ./bin
run.py                    dev-server launcher (uvicorn, reload)
requirements.txt          Python dependencies
Design Document.md        full technical design — start here
data/                     runtime state, git-ignored (registry.json · repos/ · maps/)
bin/                      the Ruff binary, created by setup.py (git-ignored)
```

---

## API

All routes are mounted under `/api`.

| Method & path | Purpose |
|---|---|
| `GET  /api/health` | Liveness + version. |
| `GET  /api/projects` | List tracked projects. |
| `POST /api/projects` | Connect a repo (clone + detect default branch). |
| `GET  /api/projects/{id}` | Fetch one project. |
| `DELETE /api/projects/{id}` | Stop tracking; remove its clone and map. |
| `GET  /api/projects/{id}/map` | Return the stored map (or a not-built marker). |
| `POST /api/projects/{id}/map` | Build the map (runs the climb; needs an API key). |
| `GET  /api/projects/{id}/branches` | Branches available to compare. |
| `POST /api/projects/{id}/compare` | Three-dot `base...compare` diff. |
| `POST /api/projects/{id}/review` | Full review → per-axis findings (needs an API key). |

---

## Design & scope

The full rationale for every decision above — the two-phase model, why the
evidence is partitioned before any agent sees it, why the map is a climb rather
than one LLM output, why invariants are human-ratified, and what is deliberately
narrated rather than built — is in [`Design Document.md`](./Design%20Document.md).
It is the north star; this README tracks the state of the code against it.