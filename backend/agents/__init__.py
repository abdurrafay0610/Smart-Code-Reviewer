"""
The intelligence layer: DeepSeek-backed agents (Design §6, §7, §8).

Public surface:

    query_deepseek        the single low-level DeepSeek entry point
    BaseAgent             base class for one bounded model task (subclass this)
    ReviewAgent           shared base for the three axis agents
    ReadabilityAgent / StructureAgent / MaintainabilityAgent
    ReviewInput           the input payload for a review agent
    AgentResult / AgentFinding
    EvidenceBundle / ProjectMap / ToolFinding / DriftFinding  (input shapes)
    stubs                 stubbed inputs until the tool layer and map engine land
"""

from __future__ import annotations

from . import stubs
from .base import AgentResponseError, BaseAgent
from .deepseek_client import (
    DeepSeekIncompleteResponseError,
    DeepSeekResponse,
    StepLogger,
    query_deepseek,
)
from .review_agents import (
    REVIEW_AGENTS,
    MaintainabilityAgent,
    ReadabilityAgent,
    ReviewAgent,
    ReviewInput,
    StructureAgent,
)
from .types import (
    AgentFinding,
    AgentResult,
    Axis,
    DriftFinding,
    EvidenceBundle,
    FileRole,
    Invariant,
    ProjectMap,
    Severity,
    ToolFinding,
)

__all__ = [
    "query_deepseek",
    "DeepSeekResponse",
    "DeepSeekIncompleteResponseError",
    "StepLogger",
    "BaseAgent",
    "AgentResponseError",
    "ReviewAgent",
    "ReviewInput",
    "ReadabilityAgent",
    "StructureAgent",
    "MaintainabilityAgent",
    "REVIEW_AGENTS",
    "AgentResult",
    "AgentFinding",
    "EvidenceBundle",
    "ProjectMap",
    "ToolFinding",
    "DriftFinding",
    "Invariant",
    "FileRole",
    "Axis",
    "Severity",
    "stubs",
]
