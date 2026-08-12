"""Rollout request/result contracts for same-turn v1 and future opponent/multi-turn.

V1 implements only ``SameTurnHorizon`` with no opponent policy. Future offline
oracle / live belief opponent policies and multi-turn horizons reuse these
types; they are not implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Protocol

HORIZON_ONE_PLAYER_TURN = "1_player_turn"
OPPONENT_POLICY_NONE = "none"
INFORMATION_PUBLIC = "public_decision"
INFORMATION_ORACLE = "oracle_hidden_state"
INFORMATION_BELIEF = "belief_hidden_state"

InformationMode = Literal["public_decision", "oracle_hidden_state", "belief_hidden_state"]
OpponentPolicyName = Literal["none", "oracle", "belief"]
HorizonName = Literal["1_player_turn", "multi_turn"]


@dataclass(frozen=True)
class SameTurnHorizon:
    """V1: search only the acting player's current turn."""

    name: HorizonName = HORIZON_ONE_PLAYER_TURN
    opponent_policy: OpponentPolicyName = OPPONENT_POLICY_NONE
    information_mode: InformationMode = INFORMATION_PUBLIC
    max_plies: int = 1


@dataclass(frozen=True)
class RolloutRequest:
    """Inputs for a (possibly multi-turn) offline or live rollout."""

    root_state_hash: str
    seat: int
    horizon: SameTurnHorizon = field(default_factory=SameTurnHorizon)
    seed: Optional[int] = None
    node_budget: int = 2000
    time_budget_ms: int = 5000
    max_depth: int = 12
    top_n: int = 20
    profile_json: Optional[str] = None
    overlay: Optional[dict[str, Any]] = None
    seed_moves: Optional[list[str]] = None


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "horizon": self.horizon,
            "opponent_policy": self.opponent_policy,
            "information_mode": self.information_mode,
            "root_state_hash": self.root_state_hash,
            "candidate_lines": self.candidate_lines,
            "search_stats": self.search_stats,
            "assumptions": self.assumptions,
            "error": self.error,
        }


class TurnPolicy(Protocol):
    """Future: run a fresh policy from a branched state (never replay history blindly)."""

    name: str
    information_mode: InformationMode

    def search_turn(self, request: RolloutRequest) -> RolloutResult:
        ...


class OracleOpponentPolicy:
    """Future offline: use the captured real opponent hand. Not implemented in v1."""

    name = "oracle"
    information_mode: InformationMode = INFORMATION_ORACLE

    def search_turn(self, request: RolloutRequest) -> RolloutResult:
        return RolloutResult(
            ok=False,
            horizon=request.horizon.name,
            opponent_policy=self.name,
            information_mode=self.information_mode,
            root_state_hash=request.root_state_hash,
            error="oracle_opponent_policy_not_implemented",
            assumptions={"note": "v1 does not simulate the opponent"},
        )


class BeliefOpponentPolicy:
    """Future live: sample hidden hands and aggregate. Not implemented in v1."""

    name = "belief"
    information_mode: InformationMode = INFORMATION_BELIEF

    def search_turn(self, request: RolloutRequest) -> RolloutResult:
        return RolloutResult(
            ok=False,
            horizon=request.horizon.name,
            opponent_policy=self.name,
            information_mode=self.information_mode,
            root_state_hash=request.root_state_hash,
            error="belief_opponent_policy_not_implemented",
            assumptions={"note": "v1 does not simulate the opponent"},
        )


def v1_assumptions() -> dict[str, Any]:
    return {
        "horizon": HORIZON_ONE_PLAYER_TURN,
        "opponent_policy": OPPONENT_POLICY_NONE,
        "information_mode": INFORMATION_PUBLIC,
        "note": (
            "V1 searches only the acting player's current turn. Defensive claims "
            "that depend on the opponent's next turn must abstain."
        ),
    }
