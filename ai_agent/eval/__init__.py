"""Riftbound AI evaluation package.

Frozen-position replay, layered graders, architecture profiles, and paired
arena pilots. Generated run artifacts live outside live ``agent_memory.db``.
"""

from .schemas import (
    EVAL_SCHEMA_VERSION,
    AgentProfile,
    EvalCase,
    EvalRunManifest,
)

__all__ = [
    "EVAL_SCHEMA_VERSION",
    "AgentProfile",
    "EvalCase",
    "EvalRunManifest",
]
