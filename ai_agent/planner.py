from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .schemas import Plan

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """\
You are the Riftbound TURN PLANNER for one seat.

## Goal
Win by reaching 8 victory points before the opponent. Points come from
controlling battlefields (Hold scores each turn; Conquer takes them). Plan to
build board presence, contest the opponent's battlefields, protect your own,
and advance score — do not stall.

## Your role (planner, NOT actor)
- You produce ONE stable strategic plan for the WHOLE turn, not a single move.
- A turn has many decisions (play, move, showdown focus, choices). Your plan is
  the shared intent every later decision should stay consistent with.
- You do NOT pick exact commands or guarantee legality — the Actor stage selects
  a concrete legal move and the engine validates it. Set direction, priorities,
  and guardrails only.

## Rules guardrails (enough to plan well)
- Battlefields are the win engine: holding them scores points each turn.
- Moving a unit into an uncontrolled/enemy battlefield can trigger a Showdown
  (combat is simultaneous and symmetric — attackers take return damage).
- Units enter exhausted at base unless Accelerate; they act on a later turn.
- Resources are runes (Energy by tapping, Power by recycling). Treat costs as
  approximate for planning; the Actor confirms what is actually affordable.
- Never assume hidden information you are not entitled to.

## Output discipline
Respond with ONE JSON object matching the Plan schema and NOTHING else — no
markdown fences, no prose. Required keys must always be present; include
optional keys only when they add real signal (e.g. set target_profile.kind to
"none" for broad development turns with no specific target).
"""

_VOLATILE_KEYS = {
    "legal_moves",
    "legal_action_categories",
    "pending_choice_options",
    "pending_choice_context",
    "decision_type",
    "current_state",
    "i_have_focus",
    "i_have_priority",
    "focus_player_index",
    "priority_player_index",
    "combat_assignment_active",
    "remaining_attacker_might",
    "damage_assigned",
    "full_state_text",
}


def strategic_state_hash(brief_state: dict[str, Any]) -> str:
    strategic = {k: v for k, v in brief_state.items() if k not in _VOLATILE_KEYS}
    serialised = json.dumps(strategic, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


@dataclass
class _CachedPlan:
    turn: int
    strategic_hash: str
    plan: Plan


class Planner:
    def __init__(self) -> None:
        self._cache: dict[str, _CachedPlan] = {}
        self._last_intent: dict[str, str] = {}

    def _cached(self, game_id: str, turn: int, strategic_hash: str) -> Plan | None:
        cached = self._cache.get(game_id)
        if not cached:
            return None
        if cached.turn == turn and cached.strategic_hash == strategic_hash:
            return cached.plan
        return None

    async def plan(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        game_id: str,
        brief_state: dict[str, Any],
        memory_summary: str,
    ) -> Plan:
        turn = int(brief_state.get("turn_number", 0))
        strategic_hash = strategic_state_hash(brief_state)
        cached = self._cached(game_id, turn, strategic_hash)
        if cached is not None:
            return cached

        plan = await _request_plan(
            client=client,
            model=model,
            brief_state=brief_state,
            memory_summary=memory_summary,
            last_intent=self._last_intent.get(game_id),
        )

        self._cache[game_id] = _CachedPlan(
            turn=turn,
            strategic_hash=strategic_hash,
            plan=plan,
        )
        self._last_intent[game_id] = plan.intent
        return plan


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        return "\n".join(
            line for line in content.splitlines()
            if not line.strip().startswith("```")
        ).strip()
    return content


def _parse_plan(content: str) -> Plan | None:
    try:
        return Plan.model_validate(json.loads(_strip_fences(content)))
    except Exception as exc:
        logger.warning("Plan parse failed: %s", exc)
        return None


def _planner_state_summary(brief_state: dict[str, Any]) -> str:
    return json.dumps(
        {
            "turn_number": brief_state.get("turn_number", 0),
            "decision_type": brief_state.get("decision_type", ""),
            "current_phase": brief_state.get("current_phase", ""),
            "my_score": brief_state.get("my_score", 0),
            "opponent_score": brief_state.get("opponent_score", 0),
            "my_hand_count": len(brief_state.get("my_hand", []) or []),
            "my_base_units": [u.get("instance_id", "") for u in brief_state.get("my_base_units", []) or []],
            "opponent_base_units": [u.get("instance_id", "") for u in brief_state.get("opponent_base_units", []) or []],
            "battlefields": [
                {
                    "battlefield_id": bf.get("battlefield_id", ""),
                    "controller_index": bf.get("controller_index", -1),
                    "my_units": [u.get("instance_id", "") for u in bf.get("my_units", []) or []],
                    "opponent_units": [u.get("instance_id", "") for u in bf.get("opponent_units", []) or []],
                }
                for bf in brief_state.get("battlefields", []) or []
            ],
        },
        indent=2,
    )


async def _request_plan(
    *,
    client: AsyncOpenAI,
    model: str,
    brief_state: dict[str, Any],
    memory_summary: str,
    last_intent: str | None,
) -> Plan:
    system = PLANNER_SYSTEM_PROMPT
    user = (
        "Create a plan for this turn with stable strategy and constraints.\n\n"
        "Required keys:\n"
        "- schema_version (string, always '2.0')\n"
        "- intent (develop_board|pressure_battlefield|stabilize_board|protect_lead|set_up_showdown|resource_setup|flexible_response)\n"
        "- plan_for_turn (short sentence)\n"
        "- priority_order (non-empty list[str])\n"
        "- hard_constraints (non-empty list[str])\n\n"
        "Optional keys:\n"
        "- focus_battlefields (list[str])\n"
        "- anchor_cards (list[str])\n"
        "- target_profile ({kind: none|battlefield|unit|card|player, ids: list[str]})\n"
        "- contingencies ([{trigger, adjustment}])\n"
        "- tactical_flexibility (low|medium|high)\n\n"
        f"Previous turn intent: {last_intent or 'none'}\n\n"
        f"Recent timeline:\n{memory_summary or '(none)'}\n\n"
        f"Strategic state:\n{_planner_state_summary(brief_state)}"
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for _ in range(2):
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "text"},
        )
        content = response.choices[0].message.content or ""
        plan = _parse_plan(content)
        if plan is not None:
            return plan
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                "Your response did not match schema. "
                "Return only valid Plan JSON with all required keys."
            ),
        })

    return Plan(
        intent="flexible_response",
        plan_for_turn="Take a legal low-risk line while preserving options.",
        priority_order=["legality", "tempo"],
        hard_constraints=["must_be_legal"],
        tactical_flexibility="high",
    )
