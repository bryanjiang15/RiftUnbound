"""
Riftbound AI Agent — JSON Schemas (schema_version 1.0)

Three schemas versioned together:
  BriefState  — compact game state snapshot sent from Godot to the agent
  Decision    — the agent's output (reasoning + move)
  Move        — a single game action with parameters

All three are Pydantic models. They must be frozen together; any change bumps
SCHEMA_VERSION and requires matching updates in BriefStateSerializer.gd.
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.0"

# ── Primitives ────────────────────────────────────────────────────────────────


class PowerCost(BaseModel):
    domain: str
    amount: int


class RuneInfo(BaseModel):
    rune_index: int
    domain: str
    is_exhausted: bool


class HandCard(BaseModel):
    instance_id: str
    name: str
    card_type: str  # unit | gear | spell | rune
    energy_cost: int
    power_cost: list[PowerCost]
    might: Optional[int] = None
    keywords: list[str] = Field(default_factory=list)
    is_reaction: bool = False
    is_action: bool = False
    effect_text: str = ""


class UnitSummary(BaseModel):
    instance_id: str
    name: str
    current_might: int
    base_might: int
    location: str  # "base" | "battlefield-a" | "battlefield-b"
    is_exhausted: bool
    is_stunned: bool
    damage: int
    buff_counters: int
    keywords: list[str] = Field(default_factory=list)
    is_attacker: bool = False
    is_defender: bool = False
    effect_text: str = ""


class BattlefieldInfo(BaseModel):
    battlefield_id: str
    display_name: str
    controller_index: int  # -1 = uncontrolled
    my_units: list[UnitSummary]
    opponent_units: list[UnitSummary]
    is_contested: bool
    has_facedown: bool
    effect_text: str = ""


# ── BriefState ────────────────────────────────────────────────────────────────

DecisionType = Literal[
    "mulligan",
    "main_phase",
    "showdown_focus",
    "chain_reaction",
    "combat_assignment",
    "pending_choice",
]


class BriefState(BaseModel):
    schema_version: str = SCHEMA_VERSION
    game_id: str
    turn_number: int
    my_player_index: int
    turn_player_index: int
    current_phase: str
    current_state: str
    decision_type: DecisionType

    # Resources
    my_score: int
    my_energy: int
    my_power: dict[str, int]
    my_runes: list[RuneInfo]

    # My hand (full — hidden from opponent)
    my_hand: list[HandCard]

    # My board
    my_base_units: list[UnitSummary]
    my_champion: Optional[UnitSummary] = None  # champion zone, if not yet played

    # Opponent public info only
    opponent_score: int
    opponent_hand_size: int
    opponent_base_units: list[UnitSummary]

    # Battlefields
    battlefields: list[BattlefieldInfo]

    # Enumerated legal moves (populated per-trigger from Godot)
    legal_moves: list[str] = Field(default_factory=list)
    legal_action_categories: list[str] = Field(default_factory=list)

    # Pending choice context
    pending_choice_options: list[str] = Field(default_factory=list)

    # Combat damage assignment context
    combat_assignment_active: bool = False
    remaining_attacker_might: int = 0
    damage_assigned: dict[str, int] = Field(default_factory=dict)

    # Full board text description (populated by Godot on push)
    full_state_text: Optional[str] = None


# ── Move ─────────────────────────────────────────────────────────────────────

ActionType = Literal[
    "mulligan_keep",
    "mulligan",
    "play_card",
    "move_unit",
    "pass",
    "end_turn",
    "use_ability",
    "react",
    "assign_damage",
    "assign_done",
    "choose",
    "choose_none",
]


class Move(BaseModel):
    action: ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)

    def to_command(self) -> str:
        """Translate a Move into a Godot console command string."""
        p = self.parameters
        if self.action == "mulligan_keep":
            return "mulligan keep"
        elif self.action == "mulligan":
            ids = " ".join(p.get("card_ids", []))
            return f"mulligan {ids}" if ids else "mulligan keep"
        elif self.action == "play_card":
            cmd = f"play {p.get('card_id', '')}"
            if p.get("destination"):
                cmd += f" to {p['destination']}"
            if p.get("target_id"):
                cmd += f" target {p['target_id']}"
            if p.get("from_champion"):
                cmd += " from champion"
            if p.get("from_hidden"):
                cmd += " from hidden"
            if p.get("accelerate"):
                cmd += " accelerate"
            return cmd
        elif self.action == "move_unit":
            unit_ids = p.get("unit_ids", [])
            if isinstance(unit_ids, str):
                unit_ids = [unit_ids]
            ids_str = " ".join(unit_ids)
            dest = p.get("destination", "base")
            return f"move {ids_str} to {dest}"
        elif self.action == "pass":
            return "pass"
        elif self.action == "end_turn":
            return "end turn"
        elif self.action == "use_ability":
            cmd = f"use {p.get('card_id', '')}"
            if p.get("target_id"):
                cmd += f" target {p['target_id']}"
            return cmd
        elif self.action == "react":
            cmd = f"react {p.get('card_id', '')}"
            if p.get("target_id"):
                cmd += f" target {p['target_id']}"
            return cmd
        elif self.action == "assign_damage":
            return f"assign {p.get('amount', 0)} to {p.get('target_id', '')}"
        elif self.action == "assign_done":
            return "assign done"
        elif self.action == "choose":
            return f"choose {p.get('target_id', '')}"
        elif self.action == "choose_none":
            return "choose none"
        else:
            return "pass"


# ── Decision ──────────────────────────────────────────────────────────────────


class Decision(BaseModel):
    reasoning: str
    move: Move
    confidence: Optional[str] = None
    alternatives_considered: Optional[Union[str, list]] = None

    @field_validator("alternatives_considered", mode="before")
    @classmethod
    def coerce_list_to_str(cls, v: Any) -> Optional[str]:
        """GPT often returns this as a list despite the prompt saying string.
        Coerce to a comma-joined sentence so validation always passes."""
        if isinstance(v, list):
            return "; ".join(str(x) for x in v) if v else None
        return v


# ── Request / Rejection wrappers ──────────────────────────────────────────────


class RejectionContext(BaseModel):
    rejected_move: Move
    rejection_reason: str


class DecisionRequest(BaseModel):
    brief_state: BriefState
    game_id: str
    rejection_context: Optional[RejectionContext] = None
