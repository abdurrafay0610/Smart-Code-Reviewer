"""
Deterministic module dependency graph — a new deterministic rung of the climb
(Design §7.2, extending §2 principle #1).

Rung 2a already extracted every file's imports. This turns those imports into a
*module-level dependency graph* entirely in code — resolving each import to the
module it targets and aggregating to directory granularity — so the architecture
step (rung 3) no longer has to *infer* the dependency structure by reading every
file's imports. It is handed the graph as ground truth and only has to interpret
it (name the layers, judge the direction).

Two payoffs, both aimed at the token-budget problem:
  * the architecture call's INPUT shrinks from the full imports-laden file table
    to a compact edge list, and
  * it has far less to reason about, so it spends far fewer thinking tokens.

Module = a file's parent directory (its Python package, in practice). Relative
imports resolve by path arithmetic against the file's own package; absolute
imports resolve by longest-prefix match against the known source paths, so
stdlib/third-party imports (which match nothing internal) fall away as external.
"""

from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath

_ROOT = "(root)"


def module_of(path: str) -> str:
    """The module a file belongs to: its parent directory, or ``(root)``."""
    parent = str(PurePosixPath(path).parent)
    return _ROOT if parent in (".", "") else parent


def _dirs_from(paths: list[str]) -> set[str]:
    """Every directory that appears as a prefix of a source path."""
    dirs: set[str] = set()
    for path in paths:
        parent = PurePosixPath(path).parent
        while str(parent) not in (".", ""):
            dirs.add(str(parent))
            parent = parent.parent
    return dirs


def _resolve(
    importer: str, imp: str, files: set[str], dirs: set[str]
) -> str | None:
    """Resolve one import to the module (directory) it targets, or None.

    ``None`` means the import points outside the repo (stdlib/third-party) or
    can't be located — either way it contributes no internal edge.
    """
    if imp.startswith("."):
        level = len(imp) - len(imp.lstrip("."))
        remainder = imp[level:]
        parts = remainder.split(".") if remainder else []
        # `.` = the importer's own package; each extra dot climbs one package up.
        anchor = PurePosixPath(importer).parent.parts
        climb = level - 1
        anchor = anchor[: len(anchor) - climb] if climb <= len(anchor) else ()
        full = list(anchor) + parts
    else:
        # Absolute import: dotted name maps onto a repo path if it's internal.
        full = imp.split(".")

    if not full:
        return _ROOT

    joined = "/".join(full)
    parent = "/".join(full[:-1])

    # In order: a module file, a package dir, or a name imported *from* a package.
    if f"{joined}.py" in files:
        return module_of(f"{joined}.py")
    if joined in dirs:
        return joined
    if f"{parent}.py" in files:
        return module_of(f"{parent}.py")
    if parent in dirs:
        return parent

    # Relative imports are internal by definition; fall back to the anchor
    # package even when the exact target file isn't in the tracked set.
    if imp.startswith("."):
        anchor_dir = "/".join(full[:-1]) if parts else joined
        return anchor_dir or _ROOT
    return None


def build_graph(file_index: list[dict]) -> dict:
    """Build the module dependency graph from ``[{path, language, imports}]``.

    Returns ``{"modules": [{name, paths}], "edges": [{from, to, count}]}`` —
    ``edges`` aggregates file-level imports to module granularity and drops
    intra-module (self) edges. Deterministic; no model involved.
    """
    files = {entry["path"] for entry in file_index}
    dirs = _dirs_from(list(files))

    # modules -> the source files they contain
    modules: dict[str, list[str]] = {}
    for entry in file_index:
        modules.setdefault(module_of(entry["path"]), []).append(entry["path"])

    # aggregate directed edges between modules, with a count of resolved imports
    edge_counts: Counter[tuple[str, str]] = Counter()
    for entry in file_index:
        src_module = module_of(entry["path"])
        for imp in entry.get("imports", []):
            target = _resolve(entry["path"], imp, files, dirs)
            if target is None or target == src_module:
                continue  # external, unresolved, or intra-module
            edge_counts[(src_module, target)] += 1

    return {
        "modules": [
            {"name": name, "paths": sorted(paths)}
            for name, paths in sorted(modules.items())
        ],
        "edges": [
            {"from": src, "to": dst, "count": count}
            for (src, dst), count in sorted(edge_counts.items())
        ],
    }