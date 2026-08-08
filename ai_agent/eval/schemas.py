"""Evaluation case / profile / result schemas.

These are independent of ``BriefState`` schema_version. Changing an eval field
bumps ``EVAL_SCHEMA_VERSION`` only.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

EVAL_SCHEMA_VERSION = "1.0"

LabelTier = Literal["gold", "silver", "diagnostic"]
FidelityStatus = Literal["authoritative", "fidelity_limited", "excluded"]
EvalSplit = Literal["dev", "sealed", "challenge", "blocking"]
EvalLane = Literal["engine", "agent"]
DataOrigin = Literal[
    "hand_built",
    "tcg_fixture",
    "inline_test",
    "live_log",
    "self_play",
    "vs_human",
]


class HardInvariant(BaseModel):
    """A deterministic check that must pass for the trial to be valid."""

    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class AcceptableOutcome(BaseModel):
    """Gold or silver acceptance criterion for a position."""

    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    label_tier: LabelTier = "gold"


class SearchBudget(BaseModel):
    node_budget: int = 80
    time_budget_ms: int = 1000
    beam_width: int = 8
    max_depth: int = 8
    top_n: int = 8
    mode: str = "main"


class EvalProvenance(BaseModel):
    source_test: str = ""
    source_fixture: str = ""
    notes: str = ""
    engine_git: str = ""
    scoring_profile: str = "res://Data/AI/scoring_profile.json"
    created_by: str = "eval_bootstrap"


class EvalCase(BaseModel):
    """Version-controlled frozen evaluation position."""

    schema_version: str = EVAL_SCHEMA_VERSION
    case_id: str
    title: str
    summary: str
    objective: str
    desired_result: str
    fixture_path: str
    fixture_hash: str = ""
    acting_seat: int = 0
    decision_type: str = "main_phase"
    tags: list[str] = Field(default_factory=list)
    split: EvalSplit = "dev"
    eval_lane: EvalLane = "agent"
    origin: DataOrigin = "hand_built"
    fidelity_status: FidelityStatus = "authoritative"
    label_tier: LabelTier = "gold"
    difficulty: Literal["trivial", "easy", "medium", "hard", "expert"] = "medium"
    hard_invariants: list[HardInvariant] = Field(default_factory=list)
    acceptable_outcomes: list[AcceptableOutcome] = Field(default_factory=list)
    # Attractive wrong lines: if any trap matches, gold fails.
    trap_outcomes: list[AcceptableOutcome] = Field(default_factory=list)
    search_budget: SearchBudget = Field(default_factory=SearchBudget)
    oracle_budget: Optional[SearchBudget] = None
    engine_mode: str = ""
    seed_moves: list[str] = Field(default_factory=list)
    metamorphic_family: str = ""
    contested_window: bool = False
    provenance: EvalProvenance = Field(default_factory=EvalProvenance)
    setup_notes: str = ""
    exclusions: str = ""

    @field_validator("case_id")
    @classmethod
    def _kebab_case_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("case_id must be non-empty")
        return cleaned


class AblationVariant(BaseModel):
    """One architecture-specific component comparison."""

    variant_id: str
    description: str
    env: dict[str, str] = Field(default_factory=dict)
    disabled_components: list[str] = Field(default_factory=list)


class AgentProfile(BaseModel):
    """Architecture-neutral agent configuration for eval runs."""

    schema_version: str = EVAL_SCHEMA_VERSION
    profile_id: str
    title: str
    architecture: str
    adapter: Literal["argmax", "reasoner", "goals", "decision", "mock"] = "argmax"
    description: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)
    components: list[str] = Field(default_factory=list)
    ablations: list[AblationVariant] = Field(default_factory=list)
    equal_compute: dict[str, Any] = Field(default_factory=dict)


class EvalRunManifest(BaseModel):
    schema_version: str = EVAL_SCHEMA_VERSION
    run_id: str
    description: str = ""
    case_globs: list[str] = Field(default_factory=lambda: ["*.json"])
    splits: list[EvalSplit] = Field(default_factory=lambda: ["dev", "blocking"])
    profiles: list[str] = Field(default_factory=list)
    repeats: int = 1
    layers: list[str] = Field(
        default_factory=lambda: [
            "contract",
            "validity",
            "gold",
            "silver",
            "trajectory",
            "cost",
        ]
    )
    transforms: list[str] = Field(default_factory=list)
    include_fidelity_limited: bool = False
    eval_lanes: list[EvalLane] = Field(default_factory=list)
    mode: Literal["agent_only", "engine_backed", "mixed"] = "agent_only"
    # Pause between LLM-backed trials. Eval fires trials back to back, and each
    # one spends several tool rounds against the API, which is enough to trip
    # per-minute rate limits on a small quota. Ignored by non-LLM adapters.
    throttle_ms: int = 0


class LayerResult(BaseModel):
    layer: str
    passed: bool
    score: Optional[float] = None
    details: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["info", "warn", "fail"] = "info"


class TrialResult(BaseModel):
    case_id: str
    profile_id: str
    repetition: int = 0
    transform: str = "identity"
    game_id: str = ""
    decision: dict[str, Any] = Field(default_factory=dict)
    reasoner_emit: dict[str, Any] = Field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    layers: list[LayerResult] = Field(default_factory=list)
    overall_pass: bool = False
    overall_score: Optional[float] = None
    error: str = ""


class ArenaOpponent(BaseModel):
    opponent_id: str
    profile_path: str
    deck_path: str
    description: str = ""


class ArenaManifest(BaseModel):
    schema_version: str = EVAL_SCHEMA_VERSION
    run_id: str
    candidate_profile: str
    candidate_deck: str
    opponents: list[ArenaOpponent] = Field(default_factory=list)
    seed_base: int = 1000
    num_pairs: int = 2
    turn_cap: int = 200
    mode: Literal["offline_argmax", "online"] = "offline_argmax"
