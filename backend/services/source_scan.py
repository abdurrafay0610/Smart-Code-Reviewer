"""
Deterministic per-file scan — rung 2a of the map "climb" (Design §7.2).

Given the file tree (rung 1, from ``git_service.list_files``), this attaches two
pieces of *ground truth* to each source file, with no model involved:

  * ``language`` — from the file extension, and
  * ``imports``  — the modules the file depends on.

Per the design's first principle (deterministic where possible), these are
computed, not guessed. They are fed as verified facts into the LLM rungs above:
the per-file responsibility call (2b) and, crucially, the architecture-inference
call (3), where the import edges are what let the model reason about layering
without re-reading raw source.

Language support here is the *import-extraction* adapter (a sibling idea to the
tool adapter in §5): the reference language is Python, extracted robustly via the
stdlib ``ast``; other languages degrade gracefully to language-known / imports-
empty until an extractor is added. Nothing above this layer changes when one is.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# --------------------------------------------------------------------------- #
# Language detection (extension -> language). Deterministic and total: an
# unknown suffix simply yields ``None`` and the file is left out of the roles.
# --------------------------------------------------------------------------- #
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".h": "cpp",
    ".c": "c",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
}


def detect_language(path: str | Path) -> str | None:
    """Return the language for ``path`` by extension, or None if unrecognised."""
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower())


# --------------------------------------------------------------------------- #
# Import extraction. Python uses ``ast`` (correct by construction); a regex
# fallback covers files that don't parse (syntax errors, Py2, partial files) so
# a single bad file never sinks the scan.
# --------------------------------------------------------------------------- #
def extract_imports(source: str, language: str) -> list[str]:
    """Extract the imported module names from ``source`` for ``language``.

    Returns a de-duplicated, order-preserving list. Languages without an
    extractor return ``[]`` — the file still gets a language and a role, it just
    contributes no dependency edges to the architecture step.
    """
    if language == "python":
        return _dedupe(_python_imports(source))
    # Extractors for other languages slot in here (e.g. #include for C/C++).
    return []


def _python_imports(source: str) -> list[str]:
    """All modules referenced by ``import`` / ``from ... import`` statements.

    Relative imports are preserved with their leading dots (``.config``,
    ``..pkg.mod``) so intra-package edges are visible to the architecture step.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _python_imports_regex(source)

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            modules.append(f"{prefix}{node.module}" if node.module else prefix)
    return modules


_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE)
_FROM_RE = re.compile(r"^\s*from\s+(\.*[\w.]*)\s+import\s+", re.MULTILINE)


def _python_imports_regex(source: str) -> list[str]:
    """Best-effort import scan for source that ``ast`` can't parse."""
    modules = [m.split(" as ")[0].strip() for m in _IMPORT_RE.findall(source)]
    modules += [m.strip() for m in _FROM_RE.findall(source) if m.strip()]
    return modules


def _dedupe(items: list[str]) -> list[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# --------------------------------------------------------------------------- #
# The rung: scan the source files among a file tree.
# --------------------------------------------------------------------------- #
def scan_files(repo: Path, rel_paths: list[str]) -> list[dict]:
    """Return ``[{path, language, imports}]`` for the *source* files in ``rel_paths``.

    ``repo`` is the clone root; ``rel_paths`` are repo-relative (straight from
    ``git_service.list_files``). Non-source files (unknown extension) and files
    that can't be read are skipped — the file tree still records them (rung 1),
    but only source files earn a language, imports, and later a responsibility.
    """
    index: list[dict] = []
    for rel in rel_paths:
        language = detect_language(rel)
        if language is None:
            continue
        try:
            source = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        index.append(
            {
                "path": rel,
                "language": language,
                "imports": extract_imports(source, language),
            }
        )
    return index