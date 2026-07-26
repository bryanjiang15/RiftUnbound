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


class FacedownCard(BaseModel):
    instance_id: str
    name: str
    card_type: str
    effect_text: str = ""
    play_from_hidden_cost: str = "0E"


class BattlefieldInfo(BaseModel):
    battlefield_id: str
    display_name: str
    controller_index: int  # -1 = uncontrolled
    my_units: list[UnitSummary]
    opponent_units: list[UnitSummary]
    is_contested: bool
    has_facedown: bool
    my_facedown: Optional[FacedownCard] = None
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

# ── Simulation (Phase 2.5) ────────────────────────────────────────────────────
#
# Engine-truth simulation results. Produced by Godot's MoveSimulator on a cloned
# GameState and inlined into BriefState, then surfaced to the model via the
# simulate_move / simulate_line skills. Defined before BriefState because
# BriefState references SimResult / LineResult. See
# docs/Phase2_5_Engine_Truth_Simulation.md.
#
# Serialization rule (mirrors the Godot delta serializer): field order is
# normative (headline win-condition fields first, then board deltas, then
# resources/tempo), and empty collections are OMITTED — the presence of a key
# means "something of this kind changed." Pydantic models below keep the fields
# Optional/default-empty so a partial dict from Godot validates cleanly.


class ControllerChange(BaseModel):
    controller_before: str  # "me" | "opponent" | "neutral"
    controller_after: str


class UnitDamage(BaseModel):
    id: str
    damage: int


class UnitMove(BaseModel):
    id: str
    to: str


class UnitBuff(BaseModel):
    id: str
    might_after: int


class ResolvedState(BaseModel):
    """The deterministic all-pass resolution of a move/line (classes A+B).

    Every field traces to an engine-mutable domain field (see §3.4 of the design
    doc). Collections default empty and are omitted by the Godot serializer when
    empty; the model tolerates their absence.
    """

    # ── headline: win condition ──
    wins_game: bool = False
    conquer: bool = False
    my_score_after: int = 0
    opp_score_after: int = 0

    # ── board deltas (omit-empty on the wire) ──
    battlefields: dict[str, ControllerChange] = Field(default_factory=dict)
    trade: Optional[str] = None
    units_killed: list[str] = Field(default_factory=list)
    units_damaged: list[UnitDamage] = Field(default_factory=list)
    my_units_surviving: list[str] = Field(default_factory=list)
    units_moved: list[UnitMove] = Field(default_factory=list)
    units_buffed: list[UnitBuff] = Field(default_factory=list)
    units_stunned: list[str] = Field(default_factory=list)

    # ── resources / tempo ──
    cards_drawn: Union[list[str], int] = 0
    cards_discarded: list[str] = Field(default_factory=list)
    energy_spent: int = 0
    exhausted: list[str] = Field(default_factory=list)
    next_decision: str = ""


class ResponseWindow(BaseModel):
    """A class-C branch point: where the opponent could legally respond.

    The simulator auto-passes these (the deterministic optimistic closure) and
    records them so the agent knows exactly where the line depends on the
    opponent doing nothing. The opponent's hidden choice is never resolved.
    """

    after_move: str = ""
    opponent_may_respond: bool = True
    legal_response_classes: list[str] = Field(default_factory=list)
    opponent_unknown_cards: int = 0
    opponent_potential_energy: int = 0
    note: str = ""


class SimResult(BaseModel):
    """Result of simulating a single move to quiescence."""

    legal: bool
    resolved_if_unanswered: Optional[ResolvedState] = None
    response_window: Optional[ResponseWindow] = None
    error: Optional[str] = None


class LineResult(BaseModel):
    """Result of simulating a scripted multi-step line (the agent's own moves)."""

    legal: bool
    applied_moves: list[str] = Field(default_factory=list)
    stopped_reason: str = ""  # quiescence | ply_budget | agent_choice | illegal
    resolved_if_unanswered: Optional[ResolvedState] = None
    opponent_windows: list[ResponseWindow] = Field(default_factory=list)
    first_illegal_move: Optional[str] = None
    error: Optional[str] = None


class PendingChoiceContext(BaseModel):
    """Why the engine is waiting for a choose command (from BriefStateSerializer.gd)."""

    prompt_text: str = ""
    prompt_type: str = ""
    source_card_name: Optional[str] = None
    source_card_id: Optional[str] = None
    source_effect_text: Optional[str] = None
    ability_description: Optional[str] = None
    remaining_discards: Optional[int] = None
    mandatory: Optional[bool] = None


class BriefState(BaseModel):
    schema_version: str = SCHEMA_VERSION
    game_id: str
    turn_number: int
    my_player_index: int
    turn_player_index: int
    current_phase: str
    current_state: str
    decision_type: DecisionType

    # Acting context (Focus vs Priority)
    focus_player_index: int = -1
    priority_player_index: int = 0
    i_have_focus: bool = False
    i_have_priority: bool = False

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

    # Engine-truth pre-simulations (Phase 2.5, option C). Godot pre-runs each
    # single legal move (and a few auto-detected combat lines) on a clone and
    # inlines the resulting SimResult/LineResult keyed by the exact command
    # string(s). The simulate_move / simulate_line skills read these so the model
    # gets observed facts without a round-trip. Empty when sim is disabled.
    move_simulations: dict[str, SimResult] = Field(default_factory=dict)
    line_simulations: dict[str, LineResult] = Field(default_factory=dict)

    # Pending choice context
    pending_choice_options: list[str] = Field(default_factory=list)
    pending_choice_context: PendingChoiceContext = Field(default_factory=PendingChoiceContext)

    # Combat damage assignment context
    combat_assignment_active: bool = False
    remaining_attacker_might: int = 0
    damage_assigned: dict[str, int] = Field(default_factory=dict)

    # Full board text description (populated by Godot on push)
    full_state_text: Optional[str] = None


# ── Planner / router support ───────────────────────────────────────────────────

# Intent is a free-form short label the planner chooses to describe the turn's
# strategic thrust. It is intentionally NOT a fixed enum: a closed vocabulary
# pushed the planner toward generic, boilerplate intents. Suggested values
# (develop_board, pressure_battlefield, stabilize_board, protect_lead,
# set_up_showdown, resource_setup, flexible_response) are offered as guidance in
# the planner prompt, but any concise descriptor is valid.
SUGGESTED_PLAN_INTENTS = (
    "develop_board",
    "pressure_battlefield",
    "stabilize_board",
    "protect_lead",
    "set_up_showdown",
    "resource_setup",
    "flexible_response",
)

TargetKind = Literal["none", "battlefield", "unit", "card", "player"]
TacticalFlexibility = Literal["low", "medium", "high"]


class TargetProfile(BaseModel):
    kind: TargetKind = "none"
    ids: list[str] = Field(default_factory=list)


class PlanContingency(BaseModel):
    trigger: str
    adjustment: str


class Plan(BaseModel):
    schema_version: str = "2.0"
    intent: str
    plan_for_turn: str
    priority_order: list[str] = Field(min_length=1)

    focus_battlefields: list[str] = Field(default_factory=list)
    anchor_cards: list[str] = Field(default_factory=list)
    target_profile: TargetProfile = Field(default_factory=TargetProfile)
    contingencies: list[PlanContingency] = Field(default_factory=list)
    tactical_flexibility: TacticalFlexibility = "medium"


# ── Goal-oriented strategist ───────────────────────────────────────────────────
#
# The strategist (an extension of the Planner) emits a GoalSet once per turn. A
# deterministic compiler (ai_agent/goal_compiler.py) turns it into a transient
# scoring-profile OVERLAY that biases the engine search for that turn only. The
# LLM never writes raw weights — it picks WHAT to want (feature / metric / card)
# and a coarse priority; the compiler decides HOW MUCH (magnitude), with a
# whitelist + clamp so a malformed goal compiles to a no-op rather than an
# unbounded or crashing weight. See docs/Score_Tuning_And_Evolution.md §5.

GoalKind = Literal["weight_bias", "state_target", "card_target"]
GoalPriority = Literal["low", "med", "high"]
GoalComparator = Literal[">=", "<=", "=="]

# LLMs phrase these freely; normalize common synonyms to the canonical tokens so a
# valid-in-spirit goal isn't rejected over wording (e.g. priority "medium" → "med",
# comparator "at_least" → ">=").
_PRIORITY_SYNONYMS = {
    "low": "low", "lo": "low", "minor": "low",
    "med": "med", "medium": "med", "mid": "med", "normal": "med", "moderate": "med",
    "high": "high", "hi": "high", "major": "high", "critical": "high", "urgent": "high",
}
_COMPARATOR_SYNONYMS = {
    ">=": ">=", ">": ">=", "ge": ">=", "gte": ">=", "at_least": ">=", "atleast": ">=",
    "min": ">=", "minimum": ">=", "≥": ">=",
    "<=": "<=", "<": "<=", "le": "<=", "lte": "<=", "at_most": "<=", "atmost": "<=",
    "max": "<=", "maximum": "<=", "≤": "<=",
    "==": "==", "=": "==", "eq": "==", "equal": "==", "equals": "==", "exactly": "==",
}


class Goal(BaseModel):
    """One strategic goal for the current turn.

    Mechanism by ``kind``:
    - ``weight_bias`` (generic, continuous): scale an EXISTING registry weight.
      Set ``feature`` to a registry spec id (e.g. ``battlefield_control``) or a
      sub-weight ref ``battlefield_weights:battlefield-a`` / ``keyword_weights:tank``.
      ``multiplier`` is advisory; the compiler clamps it. If omitted, ``priority``
      selects the multiplier tier.
    - ``state_target`` (specific, discrete): reward reaching a board state. Set
      ``metric`` to a whitelisted feature key (e.g. ``my_ready_runes``,
      ``bf_might_margin``), ``metric_key`` for dict metrics (a battlefield id),
      plus ``comparator`` + ``threshold``. Compiled to a GRADED situational bonus
      so the search sees a gradient toward the goal, not a flat plateau.
    - ``card_target`` (specific): reward lines that play a named card. Set
      ``card_id`` (a hand instance id confirmed via get_card_detail).
    """

    id: str
    kind: GoalKind
    description: str = ""
    priority: GoalPriority = "med"

    # weight_bias
    feature: Optional[str] = None
    multiplier: Optional[float] = None

    # state_target
    metric: Optional[str] = None
    metric_key: Optional[str] = None
    comparator: Optional[GoalComparator] = None
    threshold: Optional[float] = None

    # card_target
    card_id: Optional[str] = None

    @field_validator("priority", mode="before")
    @classmethod
    def _norm_priority(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _PRIORITY_SYNONYMS.get(v.strip().lower(), "med")
        return "med"

    @field_validator("comparator", mode="before")
    @classmethod
    def _norm_comparator(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            return _COMPARATOR_SYNONYMS.get(v.strip().lower(), v)
        return v

    @field_validator("kind", mode="before")
    @classmethod
    def _norm_kind(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().lower()
        return v


class GoalSet(BaseModel):
    schema_version: str = "1.0"
    turn: int = 0
    rationale: str = ""
    goals: list[Goal] = Field(default_factory=list, max_length=4)


# ── Deliberative Reasoner ────────────────────────────────────────────────────

ReasonerEmitKind = Literal["line", "goals", "base_search_fallback"]
ReasonerConfidence = Literal["commit", "goals", "fallback"]


class ReasonerEmit(BaseModel):
    """Structured termination contract for the Phase-3 Reasoner.

    A direct line references a complete request-registry entry by canonical id.
    Goal output contains a strict non-empty GoalSet. Infrastructure failures use
    ``base_search_fallback`` rather than masquerading as model-authored goals.
    """

    schema_version: str = "1.0"
    kind: ReasonerEmitKind = "goals"
    chosen_line_id: Optional[str] = None
    confidence: ReasonerConfidence = "goals"
    goal_set: Optional[GoalSet] = None
    rationale: str = ""


# ── search_for predicate ──────────────────────────────────────────────────────

GoalCombine = Literal["all", "any", "weighted"]


class PredicateClause(BaseModel):
    """One concrete, entity-scoped condition for the ``search_for`` tool.

    Shape is shared with ``Goal``'s state_target fields, but ``metric`` is drawn
    from the concrete-state vocabulary (search_metrics.SEARCH_METRICS), not the
    scoring whitelist. ``target`` names the entity the metric is about; what it
    must be is fixed by the metric's subject (unit id / battlefield id /
    "me"|"opponent" / card id / none). See
    docs/schema/search_for_tool_schema.md §3.
    """

    metric: str
    comparator: GoalComparator = ">="
    threshold: float = 0.0
    target: Optional[str] = None
    weight: GoalPriority = "med"
    label: Optional[str] = None

    @field_validator("comparator", mode="before")
    @classmethod
    def _norm_comparator(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _COMPARATOR_SYNONYMS.get(v.strip().lower(), v)
        return ">="

    @field_validator("weight", mode="before")
    @classmethod
    def _norm_weight(cls, v: Any) -> Any:
        if isinstance(v, str):
            return _PRIORITY_SYNONYMS.get(v.strip().lower(), "med")
        return "med"


# ── Move ─────────────────────────────────────────────────────────────────────

ActionType = Literal[
    "mulligan_keep",
    "mulligan",
    "play_card",
    "hide_card",
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


class LegalActionOption(BaseModel):
    action: ActionType
    params: dict[str, Any] = Field(default_factory=dict)
    label: str
    raw_command: str


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
            dest = p.get("destination", "")
            if dest and dest != "base":
                cmd += f" to {dest}"
            if p.get("target_id"):
                cmd += f" target {p['target_id']}"
            if p.get("from_champion"):
                cmd += " from champion"
            if p.get("from_hidden"):
                cmd += " from hidden"
            if p.get("accelerate"):
                cmd += " accelerate"
            return cmd
        elif self.action == "hide_card":
            return f"hide {p.get('card_id', '')} at {p.get('battlefield_id', '')}"
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


class ScoringProfile(BaseModel):
    schema_version: str = "2.0"
    win_game: float = 1000.0
    state_weights: dict[str, float] = Field(default_factory=dict)
    action_weights: dict[str, float] = Field(default_factory=dict)
    keyword_weights: dict[str, float] = Field(default_factory=dict)
    battlefield_weights: dict[str, float] = Field(default_factory=dict)
    end_of_turn: dict[str, Any] = Field(default_factory=dict)


class CandidateLine(BaseModel):
    line_id: str
    moves: list[Union[Move, str]] = Field(default_factory=list)
    move_contexts: list[dict[str, Any]] = Field(default_factory=list)
    expected_pre_hashes: list[str] = Field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    resolved_state: dict[str, Any] = Field(default_factory=dict)
    # Concrete post-line board snapshot the search_for tool queries (units /
    # battlefields / players / turn tallies / cards_played). Emitted by
    # ScoreModel.build_search_state; see search_metrics.py.
    search_state: dict[str, Any] = Field(default_factory=dict)
    opponent_windows: list[ResponseWindow] = Field(default_factory=list)
    root_state_hash: str = ""
    legal: bool = True
    complete: bool = False
    terminal_reason: str = ""
    search_mode: str = "main"
    original_line_id: Optional[str] = None
    source_lineage: list[str] = Field(default_factory=list)


class SearchStats(BaseModel):
    mode: str = "main"
    nodes_explored: int = 0
    branches_expanded: int = 0
    transposition_hits: int = 0
    max_depth_reached: int = 0
    beam_width: int = 0
    elapsed_ms: int = 0
    stopped_reason: str = ""


# ── Decision ──────────────────────────────────────────────────────────────────


class Decision(BaseModel):
    reasoning: str
    move: Move
    confidence: Optional[str] = None
    alternatives_considered: Optional[Union[str, list]] = None
    chosen_line_id: Optional[str] = None
    selector_source: Optional[str] = None  # 'llm' | 'fallback' | 'argmax'

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
    candidate_lines: Optional[list[CandidateLine]] = None
    search_stats: Optional[SearchStats] = None
    # Raw JSON of the deciding seat's scoring profile. Sent by the engine so the
    # server attributes each captured row to the exact weights that produced it
    # (per-seat). Absent for live play → server falls back to its startup profile.
    scoring_profile_json: Optional[str] = None


class GoalsRequest(BaseModel):
    """Pre-search handshake: the engine asks for this turn's goal overlay BEFORE
    running TurnSearch, so generic (weight_bias) goals bias line generation, not
    just post-hoc selection. The server runs the strategist (cached per turn) and
    returns the compiled overlay; the same cached GoalSet is reused by the
    following /decision call so selection and generation share one overlay."""

    brief_state: BriefState
    game_id: str
    # Phase 1 (search-grounded strategist): the engine may run a cheap base-profile
    # "scout" search BEFORE this handshake and inline its top-K lines here. The
    # strategist reads them via the search_turn tool so its goals are grounded in
    # what the engine can actually achieve this turn, instead of a static snapshot.
    # Absent (older engines / scout disabled) → strategist behaves as before.
    candidate_lines: Optional[list[CandidateLine]] = None
    search_stats: Optional[SearchStats] = None


class ReasonRequest(GoalsRequest):
    """Pre-search Phase-3 Reasoner handshake.

    Shares the scout-search input contract with ``GoalsRequest`` but may return
    either a verified line or a compiled GoalSet overlay.
    """

    root_state_hash: str = ""
