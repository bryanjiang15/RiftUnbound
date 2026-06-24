from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .schemas import SUGGESTED_PLAN_INTENTS, Plan
from .system_prompt import build_system_prompt_from_modules

logger = logging.getLogger(__name__)

# Maximum ReAct tool rounds the planner may take before it must emit a plan.
# The plan is cached once per turn, so this budget is paid at most once per turn.
PLANNER_MAX_TOOL_ROUNDS = 3

PLANNER_ROLE_PREAMBLE = """\
You are the Riftbound TURN PLANNER for one seat.

## Your role (planner, NOT actor)
- You produce ONE stable strategic plan for the WHOLE turn, not a single move.
- A turn has many decisions (play, move, showdown focus, choices). Your plan is
  shared guidance that keeps those decisions broadly coherent.
- The plan is NOT binding. The Actor stage may deviate from it whenever a clearly
  better legal move appears; you set default direction and priorities, not hard
  rules.
- You do NOT pick exact commands or guarantee legality — the Actor stage selects a
  concrete legal move and the engine validates it.

## Ground every plan in the actual board — use tools, do not guess
You are given a board summary, but DETAIL lives behind tools. Prefer fetching
facts over assuming them:
- ALWAYS call `evaluate_position` first; base your `intent` on its assessment
  (score advantage, battlefield control, playable cards) rather than a default.
- BEFORE you name any card in `anchor_cards` (or build a line around it), call
  `get_card_detail` to confirm its text, cost, and keywords.
- If a keyword shown on a card is not explained in the "Keywords in play" block,
  call `get_keyword` (or `lookup_rule`) before you rely on it.
- When a rules interaction matters to the plan (combat trade math, scoring lines,
  showdown timing), call `lookup_rule` instead of approximating.
- To read the opponent's recent pattern, call `get_opponent_history`.
Make your tool calls, then commit to one concrete, board-specific plan.

## Output discipline
When you are done gathering facts, respond with ONE JSON object matching the Plan
schema and NOTHING else — no markdown fences, no prose. Required keys must always
be present; include optional keys only when they add real signal (e.g. set
target_profile.kind to "none" for broad development turns with no specific target).
"""


@dataclass
class _CachedPlan:
    turn: int
    opp_action_count: int
    plan: Plan


class Planner:
    def __init__(self) -> None:
        self._cache: dict[str, _CachedPlan] = {}
        self._last_intent: dict[str, str] = {}

    def _cached(self, game_id: str, turn: int, opp_action_count: int) -> Plan | None:
        cached = self._cache.get(game_id)
        if not cached:
            return None
        if cached.turn == turn and cached.opp_action_count == opp_action_count:
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
        opponent_action_count: int = 0,
        metrics: dict[str, Any] | None = None,
    ) -> tuple[Plan, bool]:
        """Return (plan, was_cached) for this turn.

        The per-turn plan is reused for every decision in the same turn UNLESS the
        opponent has played a card or used an ability since it was made (tracked by
        ``opponent_action_count``). Opponent passes/moves/choices do NOT invalidate
        the plan. A new turn (``turn_number``) also forces a fresh plan.

        was_cached is True when an existing plan is reused, False when a fresh
        planner LLM call produced the plan.
        """
        turn = int(brief_state.get("turn_number", 0))
        cached = self._cached(game_id, turn, opponent_action_count)
        if cached is not None:
            return cached, True

        plan = await _request_plan(
            client=client,
            model=model,
            game_id=game_id,
            brief_state=brief_state,
            memory_summary=memory_summary,
            last_intent=self._last_intent.get(game_id),
            metrics=metrics,
        )

        self._cache[game_id] = _CachedPlan(
            turn=turn,
            opp_action_count=opponent_action_count,
            plan=plan,
        )
        self._last_intent[game_id] = plan.intent
        return plan, False


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
    """Render the same rich board view the Actor sees, minus decision-local noise.

    The planner forms ONE strategy for the whole turn, so the per-decision pieces
    (the enumerated legal moves, any pending-choice prompt, combat-assignment
    bookkeeping) are stripped: anchoring the turn plan on a single decision's legal
    move set would bias it. Everything strategically load-bearing — hand with costs
    and effect text, board units with stats and keywords, battlefield control,
    resources — is shared via the Actor's renderer so planner and Actor reason from
    the same view.
    """
    # Lazy import avoids a circular import at module load (agent imports planner).
    from . import agent as agent_module

    strategic = dict(brief_state)
    strategic["legal_moves"] = []
    strategic["legal_action_categories"] = []
    strategic["pending_choice_options"] = []
    strategic["pending_choice_context"] = {}
    strategic["combat_assignment_active"] = False
    return agent_module._format_brief_state(strategic)


def _planner_system_prompt(brief_state: dict[str, Any]) -> str:
    rules = build_system_prompt_from_modules(
        ["goal_and_role", "core_rules", "keywords_in_play"],
        brief_state=brief_state,
    )
    return f"{PLANNER_ROLE_PREAMBLE}\n\n{rules}".strip()


def _planner_user_prompt(
    *,
    brief_state: dict[str, Any],
    memory_summary: str,
    last_intent: str | None,
) -> str:
    suggested = "|".join(SUGGESTED_PLAN_INTENTS)
    return (
        "Create a plan for this turn with a stable strategy and priorities. "
        "The plan is guidance, not a binding contract — the Actor may deviate "
        "when a clearly better legal move arises.\n\n"
        "Inspect the board with tools first (evaluate_position, get_card_detail, "
        "lookup_rule, get_keyword, get_opponent_history), THEN emit the plan as one "
        "JSON object.\n\n"
        "Required keys:\n"
        "- schema_version (string, always '2.0')\n"
        f"- intent (concise label; suggested: {suggested}; any short descriptor is allowed)\n"
        "- plan_for_turn (short sentence, grounded in the actual board)\n"
        "- priority_order (non-empty list[str]; reference concrete card / battlefield ids)\n\n"
        "Optional keys:\n"
        "- focus_battlefields (list[str])\n"
        "- anchor_cards (list[str]; only cards you confirmed with get_card_detail)\n"
        "- target_profile ({kind: none|battlefield|unit|card|player, ids: list[str]})\n"
        "- contingencies ([{trigger, adjustment}])\n"
        "- tactical_flexibility (low|medium|high)\n\n"
        f"Previous turn intent: {last_intent or 'none'}\n\n"
        f"Recent timeline:\n{memory_summary or '(none)'}\n\n"
        f"Strategic state:\n{_planner_state_summary(brief_state)}"
    )


async def _request_plan(
    *,
    client: AsyncOpenAI,
    model: str,
    game_id: str,
    brief_state: dict[str, Any],
    memory_summary: str,
    last_intent: str | None,
    metrics: dict[str, Any] | None = None,
) -> Plan:
    # Lazy import avoids a circular import at module load (agent imports planner).
    from . import agent as agent_module

    system = _planner_system_prompt(brief_state)
    user = _planner_user_prompt(
        brief_state=brief_state,
        memory_summary=memory_summary,
        last_intent=last_intent,
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    tool_trace: list[dict] = []

    def _finish(plan: Plan, outcome: str) -> Plan:
        agent_module._log_tools(
            game_id,
            brief_state,
            tool_trace=tool_trace,
            outcome=outcome,
            stage="planner",
        )
        return plan

    parse_retries_left = 2
    for round_index in range(PLANNER_MAX_TOOL_ROUNDS + 1):
        # Force evaluate_position on the first round so the plan's intent is
        # grounded in the actual position rather than a generic default. The
        # "only JSON" output discipline otherwise suppresses tool calls entirely.
        if round_index == 0:
            tool_choice: Any = {
                "type": "function",
                "function": {"name": "evaluate_position"},
            }
        else:
            tool_choice = "auto"
        try:
            response = await agent_module._chat_create(
                client,
                metrics=metrics,
                stage="planner",
                model=model,
                messages=messages,  # type: ignore[arg-type]
                tools=agent_module.TOOLS,  # type: ignore[arg-type]
                tool_choice=tool_choice,
                temperature=0.1,
                response_format={"type": "text"},
            )
        except agent_module.TRANSIENT_API_ERRORS as exc:
            # Rate-limited/unavailable after retries: fall back to the safe default
            # plan rather than crashing the decision. The Actor still validates the
            # actual move, so a generic plan degrades gracefully.
            logger.warning("Planner API unavailable after retries (%s); using fallback plan", type(exc).__name__)
            return _finish(
                _FALLBACK_PLAN(),
                f"fallback plan (transient API failure after retries: {type(exc).__name__})",
            )
        except Exception as exc:
            logger.error("Planner API error: %s; using fallback plan", exc)
            return _finish(_FALLBACK_PLAN(), f"fallback plan (API error: {exc})")
        msg = response.choices[0].message

        if msg.tool_calls:
            messages.append(msg)  # type: ignore[arg-type]
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool_trace.append(
                    {"round": round_index, "name": tc.function.name, "args": args}
                )
                result = agent_module._dispatch_tool(tc.function.name, args)
                result_text = json.dumps(result) if not isinstance(result, str) else result
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result_text}
                )
            continue

        content = msg.content or ""
        plan = _parse_plan(content)
        if plan is not None:
            return _finish(
                plan,
                f"plan intent='{plan.intent}' (after {len(tool_trace)} tool call(s))",
            )
        if parse_retries_left <= 0:
            break
        parse_retries_left -= 1
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": (
                "Your response did not match schema. "
                "Return only valid Plan JSON with all required keys."
            ),
        })

    return _finish(
        _FALLBACK_PLAN(),
        "fallback plan (schema never matched / rounds exhausted)",
    )


def _FALLBACK_PLAN() -> Plan:
    return Plan(
        intent="flexible_response",
        plan_for_turn="Take a legal low-risk line while preserving options.",
        priority_order=["legality", "tempo"],
        tactical_flexibility="high",
    )
