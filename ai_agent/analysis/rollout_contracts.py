"""Rollout request/result contracts for same-turn and multi-turn outcome CF.

V1 (shipped): ``SameTurnHorizon`` with no opponent policy.
V2: multi-turn oracle opponent rollouts with explicit budgets and outcome tiers.
Belief-state simulation remains deferred.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional, Protocol

HORIZON_ONE_PLAYER_TURN = "1_player_turn"
HORIZON_MULTI_TURN = "multi_turn"
OPPONENT_POLICY_NONE = "none"
OPPONENT_POLICY_ORACLE = "oracle"
OPPONENT_POLICY_BELIEF = "belief"
INFORMATION_PUBLIC = "public_decision"
INFORMATION_ORACLE = "oracle_hidden_state"
INFORMATION_BELIEF = "belief_hidden_state"

RESULT_SCHEMA_V1 = "1"
RESULT_SCHEMA_V2 = "2"

DEFAULT_FUTURE_PLAYER_TURNS = 4
HARD_CAP_FUTURE_PLAYER_TURNS = 6
DEFAULT_ROOT_ALT_CAP = 4
DEFAULT_OPPONENT_TOP_N = 3
DEFAULT_SEAT_TOP_N = 2
DEFAULT_FRONTIER_CAP = 24
DEFAULT_GLOBAL_NODE_BUDGET = 10_000
DEFAULT_GLOBAL_TIME_MS = 30_000
DEFAULT_TURN_BEAM_WIDTH = 8

InformationMode = Literal["public_decision", "oracle_hidden_state", "belief_hidden_state"]
OpponentPolicyName = Literal["none", "oracle", "belief"]
HorizonName = Literal["1_player_turn", "multi_turn"]
OutcomeTierName = Literal["possible", "policy_likely", "robust"]
RunKind = Literal["same_turn", "outcome_rollout"]
PresetName = Literal["fast", "deep"]


@dataclass(frozen=True)
class SameTurnHorizon:
    """V1: search only the acting player's current turn."""

    name: HorizonName = HORIZON_ONE_PLAYER_TURN
    opponent_policy: OpponentPolicyName = OPPONENT_POLICY_NONE
    information_mode: InformationMode = INFORMATION_PUBLIC
    max_plies: int = 1


@dataclass(frozen=True)
class MultiTurnHorizon:
    """V2: future completed player-turns after the root line."""

    name: HorizonName = HORIZON_MULTI_TURN
    opponent_policy: OpponentPolicyName = OPPONENT_POLICY_ORACLE
    information_mode: InformationMode = INFORMATION_ORACLE
    future_player_turns: int = DEFAULT_FUTURE_PLAYER_TURNS
    hard_cap: int = HARD_CAP_FUTURE_PLAYER_TURNS

    def clamped_turns(self) -> int:
        return max(1, min(int(self.future_player_turns), int(self.hard_cap)))


@dataclass(frozen=True)
class RolloutBudget:
    """Outer rollout tree budgets (distinct from per-TurnSearch budgets)."""

    frontier_cap: int = DEFAULT_FRONTIER_CAP
    global_node_budget: int = DEFAULT_GLOBAL_NODE_BUDGET
    global_time_ms: int = DEFAULT_GLOBAL_TIME_MS
    seat_top_n: int = DEFAULT_SEAT_TOP_N
    opponent_top_n: int = DEFAULT_OPPONENT_TOP_N
    root_alt_cap: int = DEFAULT_ROOT_ALT_CAP
    turn_beam_width: int = DEFAULT_TURN_BEAM_WIDTH
    per_turn_node_budget: int = 400
    per_turn_time_budget_ms: int = 800
    per_turn_max_depth: int = 12

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BUDGET_PRESETS: dict[str, RolloutBudget] = {
    "fast": RolloutBudget(
        frontier_cap=12,
        global_node_budget=3_000,
        global_time_ms=10_000,
        seat_top_n=1,
        opponent_top_n=2,
        root_alt_cap=2,
        turn_beam_width=6,
        per_turn_node_budget=120,
        per_turn_time_budget_ms=300,
        per_turn_max_depth=8,
    ),
    "deep": RolloutBudget(),
}


@dataclass(frozen=True)
class RolloutRequest:
    """Inputs for a (possibly multi-turn) offline or live rollout."""

    root_state_hash: str
    seat: int
    horizon: SameTurnHorizon | MultiTurnHorizon = field(default_factory=SameTurnHorizon)
    seed: Optional[int] = None
    node_budget: int = 2000
    time_budget_ms: int = 5000
    max_depth: int = 12
    top_n: int = 20
    profile_json: Optional[str] = None
    overlay: Optional[dict[str, Any]] = None
    seed_moves: Optional[list[str]] = None
    budget: RolloutBudget = field(default_factory=RolloutBudget)
    roots: list[dict[str, Any]] = field(default_factory=list)
    target: Optional[dict[str, Any]] = None
    preset: PresetName = "deep"


@dataclass
class RolloutResult:
    """Every result is stamped with horizon / opponent policy / information mode."""

    ok: bool
    horizon: str = HORIZON_ONE_PLAYER_TURN
    opponent_policy: str = OPPONENT_POLICY_NONE
    information_mode: str = INFORMATION_PUBLIC
    root_state_hash: str = ""
    candidate_lines: list[dict[str, Any]] = field(default_factory=list)
    search_stats: dict[str, Any] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    result_schema_version: str = RESULT_SCHEMA_V1
    run_kind: RunKind = "same_turn"
    future_player_turns: int = 0
    rollout_tree: Optional[dict[str, Any]] = None
    outcome_tiers: Optional[dict[str, Any]] = None
    same_turn_fallback: Optional[dict[str, Any]] = None
    truncated: bool = False
    stop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {
            "ok": self.ok,
            "horizon": self.horizon,
            "opponent_policy": self.opponent_policy,
            "information_mode": self.information_mode,
            "root_state_hash": self.root_state_hash,
            "candidate_lines": self.candidate_lines,
            "search_stats": self.search_stats,
            "assumptions": self.assumptions,
            "error": self.error,
            "result_schema_version": self.result_schema_version,
            "run_kind": self.run_kind,
            "future_player_turns": self.future_player_turns,
            "truncated": self.truncated,
            "stop_reason": self.stop_reason,
        }
        if self.rollout_tree is not None:
            out["rollout_tree"] = self.rollout_tree
        if self.outcome_tiers is not None:
            out["outcome_tiers"] = self.outcome_tiers
        if self.same_turn_fallback is not None:
            out["same_turn_fallback"] = self.same_turn_fallback
        return out


class TurnPolicy(Protocol):
    """Run a fresh policy from a branched state (never replay history blindly)."""

    name: str
    information_mode: InformationMode

    def search_turn(self, request: RolloutRequest) -> RolloutResult:
        ...


class OracleOpponentPolicy:
    """Offline: use the captured real opponent hand (oracle information)."""

    name = "oracle"
    information_mode: InformationMode = INFORMATION_ORACLE

    def search_turn(self, request: RolloutRequest) -> RolloutResult:
        # Implemented by Godot OutcomeRollout via TurnSearch on the opposing seat.
        # This Python stub documents the contract; callers should use /engine/rollout.
        return RolloutResult(
            ok=False,
            horizon=getattr(request.horizon, "name", HORIZON_MULTI_TURN),
            opponent_policy=self.name,
            information_mode=self.information_mode,
            root_state_hash=request.root_state_hash,
            error="oracle_opponent_policy_use_engine_rollout",
            assumptions=v2_assumptions(request),
            result_schema_version=RESULT_SCHEMA_V2,
            run_kind="outcome_rollout",
        )


class BeliefOpponentPolicy:
    """Future live: sample hidden hands and aggregate. Not implemented."""

    name = "belief"
    information_mode: InformationMode = INFORMATION_BELIEF

    def search_turn(self, request: RolloutRequest) -> RolloutResult:
        return RolloutResult(
            ok=False,
            horizon=getattr(request.horizon, "name", HORIZON_MULTI_TURN),
            opponent_policy=self.name,
            information_mode=self.information_mode,
            root_state_hash=request.root_state_hash,
            error="belief_opponent_policy_not_implemented",
            assumptions={"note": "belief opponent policy is deferred"},
        )


def v1_assumptions() -> dict[str, Any]:
    return {
        "horizon": HORIZON_ONE_PLAYER_TURN,
        "opponent_policy": OPPONENT_POLICY_NONE,
        "information_mode": INFORMATION_PUBLIC,
        "result_schema_version": RESULT_SCHEMA_V1,
        "note": (
            "V1 searches only the acting player's current turn. Defensive claims "
            "that depend on the opponent's next turn must abstain."
        ),
    }


def v2_assumptions(
    request: Optional[RolloutRequest] = None,
    *,
    future_player_turns: int = DEFAULT_FUTURE_PLAYER_TURNS,
    budget: Optional[RolloutBudget] = None,
    profile_assumption: str = "recorded_or_default",
) -> dict[str, Any]:
    b = budget or (request.budget if request is not None else RolloutBudget())
    turns = future_player_turns
    if request is not None and isinstance(request.horizon, MultiTurnHorizon):
        turns = request.horizon.clamped_turns()
    return {
        "horizon": HORIZON_MULTI_TURN,
        "opponent_policy": OPPONENT_POLICY_ORACLE,
        "information_mode": INFORMATION_ORACLE,
        "result_schema_version": RESULT_SCHEMA_V2,
        "future_player_turns": turns,
        "hard_cap_future_player_turns": HARD_CAP_FUTURE_PLAYER_TURNS,
        "root_alt_cap": b.root_alt_cap,
        "opponent_top_n": b.opponent_top_n,
        "seat_top_n": b.seat_top_n,
        "frontier_cap": b.frontier_cap,
        "global_node_budget": b.global_node_budget,
        "global_time_ms": b.global_time_ms,
        "turn_beam_width": b.turn_beam_width,
        "profile_assumption": profile_assumption,
        "policy_bounded": True,
        "note": (
            "Multi-turn rollout uses the restored oracle opponent hand/deck and "
            "re-searches both seats at every decision boundary. Retained branches "
            "are policy-bounded (top-N), not exhaustive. Claims are conditional on "
            "these assumptions — never certain blunder proof."
        ),
    }


def resolve_budget(preset: str = "deep", overrides: Optional[dict[str, Any]] = None) -> RolloutBudget:
    base = BUDGET_PRESETS.get(preset, BUDGET_PRESETS["deep"])
    if not overrides:
        return base
    data = base.to_dict()
    for key, value in overrides.items():
        if key in data and value is not None:
            data[key] = int(value)
    return RolloutBudget(**data)


def clamp_future_player_turns(value: int, hard_cap: int = HARD_CAP_FUTURE_PLAYER_TURNS) -> int:
    return max(1, min(int(value), int(hard_cap)))
