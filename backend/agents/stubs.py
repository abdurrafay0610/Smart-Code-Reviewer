"""
STUB inputs for the review agents.

The agents are real; their inputs are not wired yet. Normally:

  * the evidence bundle comes from the deterministic tool layer
    (``review_service.run_tools`` -> ``build_evidence_bundle``, Design §5), and
  * the project map comes from the map engine (``map_service``, §7.2), and
  * drift findings come from the drift check (§8).

All three are stubbed here with small, representative fixtures so the agents can
be exercised end-to-end today. The fixtures describe a tiny imagined project
(a layered ``ui/`` → ``core/`` → ``net/`` app) purely to give the agents
realistic, citable material. Replace the call sites of these functions with the
real producers when they land — the agents themselves won't change.
"""

from __future__ import annotations

from .types import (
    DriftFinding,
    EvidenceBundle,
    FileRole,
    Invariant,
    ProjectMap,
    ToolFinding,
)


def stub_project_map() -> ProjectMap:
    """A small ratified map: prose + a few invariants + a couple of file roles."""
    return ProjectMap(
        prose=(
            "A small layered C++ application. `ui/` renders and handles input; "
            "`core/` holds domain logic and data models; `net/` is the only layer "
            "that performs network I/O. Dependencies flow downward: ui -> core -> net."
        ),
        invariants=[
            Invariant(
                id="layering-ui-core",
                rule="ui/ may depend on core/, but core/ must never depend on ui/.",
                rationale="Keeps domain logic reusable and testable without the UI.",
                ratified=True,
            ),
            Invariant(
                id="net-owns-sockets",
                rule="Only net/ may open sockets or perform network I/O.",
                rationale="Centralises I/O so retries, timeouts, and mocking live in one place.",
                ratified=True,
            ),
            Invariant(
                id="core-no-io",
                rule="core/ performs no I/O (no file, socket, or console access).",
                rationale="Domain logic stays pure and unit-testable.",
                ratified=True,
            ),
        ],
        file_roles=[
            FileRole(
                path="core/order.cpp",
                language="cpp",
                responsibility="Order domain model and pricing rules.",
            ),
            FileRole(
                path="core/cache.cpp",
                language="cpp",
                responsibility="In-memory cache for computed order totals.",
            ),
            FileRole(
                path="ui/checkout_view.cpp",
                language="cpp",
                responsibility="Renders the checkout screen and handles button input.",
            ),
        ],
    )


def stub_evidence_bundle() -> EvidenceBundle:
    """Representative tool findings, already partitioned by axis (§5)."""
    return EvidenceBundle(
        readability=[
            ToolFinding(
                tool="clang-tidy",
                signal="readability-magic-numbers",
                path="core/order.cpp",
                line=42,
                message="3 is a magic number; give it a named constant.",
            ),
            ToolFinding(
                tool="clang-tidy",
                signal="readability-identifier-naming",
                path="core/order.cpp",
                line=17,
                message="Variable 'tmp2' does not follow the lowerCamelCase convention "
                "and is not descriptive.",
            ),
            ToolFinding(
                tool="clang-format",
                signal="format-diff",
                path="ui/checkout_view.cpp",
                line=88,
                message="Line exceeds the column limit and would be reflowed by clang-format.",
                metric=118,
                threshold=100,
            ),
        ],
        structure=[
            ToolFinding(
                tool="lizard",
                signal="ccn",
                path="core/order.cpp",
                line=55,
                message="Function 'applyDiscounts' has high cyclomatic complexity.",
                metric=23,
                threshold=15,
            ),
            ToolFinding(
                tool="lizard",
                signal="nloc",
                path="core/order.cpp",
                line=55,
                message="Function 'applyDiscounts' is long.",
                metric=140,
                threshold=100,
            ),
            ToolFinding(
                tool="clang-tidy",
                signal="readability-function-cognitive-complexity",
                path="core/order.cpp",
                line=55,
                message="Deeply nested branches make 'applyDiscounts' hard to follow.",
                metric=31,
                threshold=25,
            ),
        ],
        maintainability=[
            ToolFinding(
                tool="cppcheck",
                signal="nullPointerRedundantCheck",
                path="core/cache.cpp",
                line=63,
                message="Possible null-pointer dereference of 'entry' after it is used.",
                severity="high",
            ),
            ToolFinding(
                tool="clang-tidy",
                signal="modernize-use-auto",
                path="core/cache.cpp",
                line=29,
                message="Use 'auto' for the iterator declaration to reduce redundancy.",
            ),
            ToolFinding(
                tool="lizard",
                signal="duplicate",
                path="core/cache.cpp",
                line=70,
                message="Duplicated block: 'core/cache.cpp:70-95' closely matches "
                "'core/order.cpp:120-145'.",
            ),
        ],
    )


def stub_drift_findings() -> list[DriftFinding]:
    """
    One representative drift finding (§8): core/ opening a socket violates the
    ratified 'net-owns-sockets' (and 'core-no-io') invariants. It routes to the
    Structure and Maintainability agents.
    """
    return [
        DriftFinding(
            invariant_id="net-owns-sockets",
            invariant_rule="Only net/ may open sockets or perform network I/O.",
            path="core/cache.cpp",
            line=82,
            explanation=(
                "core/cache.cpp opens a TCP socket to fetch remote totals. Network "
                "I/O belongs in net/; core/ should depend on a net/ interface instead."
            ),
        ),
    ]
