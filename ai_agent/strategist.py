"""
Goal-oriented strategist — emits one GoalSet per turn.

This is the planner's sibling: where the Planner produces advisory prose for the
Actor, the Strategist produces a STRUCTURED GoalSet that the goal compiler turns
into a transient scoring-profile overlay biasing the engine search. It runs at
most once per turn (cached, invalidated only when the opponent acts), so its LLM
cost is amortized over every decision in the turn.

Design note (context sizing): the strategist is given the SAME rules depth as the
planner (goal/role + core rules + keywords in play) — NOT the detailed combat /
priority modules, which are tactical and owned by the search. Its one extra,
load-bearing context block is the goal-vocabulary menu, so it references real
features/metrics instead of hallucinating terms that would compile to no-ops.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI

from .prompts import load_prompt
from .schemas import Goal, GoalSet
from .system_prompt import build_system_prompt_from_modules

logger = logging.getLogger(__name__)

STRATEGIST_MAX_TOOL_ROUNDS = 3

_STRATEGIST_ROLE_BASE = load_prompt("strategist_role_base")

# Think-phase discipline (think/format split): free the model to deliberate. The
# strict GoalSet JSON is produced by a SEPARATE format call, so here the model
# should reason openly and end with a concrete recommendation in prose.
_OUTPUT_DISCIPLINE_THINK = load_prompt("strategist_output_discipline_think")


@dataclass
class _CachedGoals:
    turn: int
    opp_action_count: int
    goal_set: GoalSet


class Strategist:
    def __init__(self) -> None:
        self._cache: dict[str, _CachedGoals] = {}

    def _cached(self, game_id: str, turn: int, opp_action_count: int) -> GoalSet | None:
        cached = self._cache.get(game_id)
        if cached and cached.turn == turn and cached.opp_action_count == opp_action_count:
            return cached.goal_set
        return None

    async def goals(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        game_id: str,
        brief_state: dict[str, Any],
        memory_summary: str = "",
        opponent_action_count: int = 0,
        metrics: dict[str, Any] | None = None,
        has_scout_lines: bool = False,
    ) -> tuple[GoalSet, bool]:
        """Return (goal_set, was_cached) for this turn."""
        turn = int(brief_state.get("turn_number", 0))
        cached = self._cached(game_id, turn, opponent_action_count)
        if cached is not None:
            return cached, True
        goal_set = await _request_goals(
            client=client,
            model=model,
            game_id=game_id,
            brief_state=brief_state,
            memory_summary=memory_summary,
            metrics=metrics,
            has_scout_lines=has_scout_lines,
        )
        self._cache[game_id] = _CachedGoals(turn, opponent_action_count, goal_set)
        return goal_set, False


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        return "\n".join(
            line for line in content.splitlines() if not line.strip().startswith("```")
        ).strip()
    return content


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block in ``text``, or None.

    Tolerates a model that wraps its JSON in prose despite the output contract.
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_goals(content: str) -> GoalSet | None:
    """Parse a GoalSet leniently.

    Robustness measures (the model is an LLM, not a serializer):
    - strip markdown fences; if that still isn't pure JSON, extract the first
      balanced ``{...}`` block from surrounding prose.
    - validate goals INDIVIDUALLY and keep the valid ones, so a single malformed
      goal (bad metric, missing field) does not discard an otherwise good set.
    Returns None only when no JSON object can be found at all (caller retries).
    """
    raw = _strip_fences(content)
    data: Any = None
    for candidate in (raw, _extract_json_object(raw)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if not isinstance(data, dict):
        logger.warning("GoalSet parse failed: no JSON object in content")
        return None

    raw_goals = data.get("goals", [])
    if not isinstance(raw_goals, list):
        raw_goals = []
    good: list[Goal] = []
    for i, g in enumerate(raw_goals):
        try:
            good.append(Goal.model_validate(g))
        except Exception as exc:  # noqa: BLE001 — skip just this goal
            logger.warning("Dropping invalid goal[%d]: %s", i, exc)
    try:
        return GoalSet(
            schema_version=str(data.get("schema_version", "1.0")),
            turn=int(data.get("turn", 0) or 0),
            rationale=str(data.get("rationale", "")),
            goals=good[:4],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("GoalSet assembly failed: %s", exc)
        return None


def _chat_kwargs(**kwargs: Any) -> dict[str, Any]:
    """Assemble chat.completions kwargs, dropping params a reasoning model rejects.

    Reasoning models (o-series, gpt-5) only accept the default temperature, so it
    is omitted for them rather than sent and rejected. The model is read from
    ``kwargs['model']``.
    """
    from . import agent as agent_module

    if agent_module._is_reasoning_model(str(kwargs.get("model", ""))):
        kwargs.pop("temperature", None)
    return kwargs


def _strategist_system_prompt(brief_state: dict[str, Any]) -> str:
    rules = build_system_prompt_from_modules(
        ["goal_and_role", "core_rules", "keywords_in_play", "goal_vocabulary"],
        brief_state=brief_state,
    )
    preamble = f"{_STRATEGIST_ROLE_BASE}\n\n{_OUTPUT_DISCIPLINE_THINK}\n"
    return f"{preamble}\n\n{rules}".strip()


def _strategist_user_prompt(*, brief_state: dict[str, Any], memory_summary: str) -> str:
    from . import agent as agent_module

    strategic = dict(brief_state)
    strategic["legal_moves"] = []
    strategic["legal_action_categories"] = []
    task = load_prompt("strategist_task")
    return (
        f"{task}\n\n"
        f"Recent timeline:\n{memory_summary or '(none)'}\n\n"
        f"Strategic state:\n{agent_module._format_brief_state(strategic)}"
    )


# Format phase (think/format split): turn the think-phase reasoning into a strict
# GoalSet JSON object. No tools, no further reasoning — pure serialization.
_FORMAT_PHASE_INSTRUCTION = load_prompt("strategist_format_phase")


async def _request_goals(
    *,
    client: AsyncOpenAI,
    model: str,
    game_id: str,
    brief_state: dict[str, Any],
    memory_summary: str,
    metrics: dict[str, Any] | None = None,
    has_scout_lines: bool = False,
) -> GoalSet:
    from . import agent as agent_module

    turn = int(brief_state.get("turn_number", 0))
    system = _strategist_system_prompt(brief_state)
    user = _strategist_user_prompt(brief_state=brief_state, memory_summary=memory_summary)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    tool_trace: list[dict] = []

    def _finish(goal_set: GoalSet, outcome: str) -> GoalSet:
        agent_module._log_tools(game_id, brief_state, tool_trace=tool_trace, outcome=outcome, stage="strategist")
        return goal_set

    # Round 0 forces a grounding tool so goals are never set blind: search_turn
    # when a scout search seeded the engine's best lines (Phase 1), else
    # evaluate_position. The name is resolved once here to keep the loop simple.
    grounding_tool = "search_turn" if has_scout_lines else "evaluate_position"

    # Phase A — gather facts and deliberate. The loop yields free-form reasoning;
    # the strict GoalSet is produced by the format phase below.
    for round_index in range(STRATEGIST_MAX_TOOL_ROUNDS + 1):
        # Round 0: force the grounding tool. Final round: force a text answer
        # (tool_choice="none") so the model can't keep calling tools and leave us
        # with empty content. Middle rounds: free tool use.
        if round_index == 0:
            tool_choice: Any = {"type": "function", "function": {"name": grounding_tool}}
        elif round_index == STRATEGIST_MAX_TOOL_ROUNDS:
            tool_choice = "none"
        else:
            tool_choice = "auto"
        try:
            response = await agent_module._chat_create(
                client,
                metrics=metrics,
                stage="strategist",
                **_chat_kwargs(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    tools=agent_module.TOOLS,  # type: ignore[arg-type]
                    tool_choice=tool_choice,
                    temperature=0.1,
                    response_format={"type": "text"},
                ),
            )
        except agent_module.TRANSIENT_API_ERRORS as exc:
            logger.warning("Strategist API unavailable after retries (%s); empty goals", type(exc).__name__)
            return _finish(_EMPTY_GOALS(turn), f"empty goals (transient API failure: {type(exc).__name__})")
        except Exception as exc:  # noqa: BLE001
            logger.error("Strategist API error: %s; empty goals", exc)
            return _finish(_EMPTY_GOALS(turn), f"empty goals (API error: {exc})")

        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(msg)  # type: ignore[arg-type]
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result_text = agent_module._invoke_traced_tool(
                    tool_trace,
                    round_num=round_index,
                    name=tc.function.name,
                    args=args,
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_text})
            continue

        content = msg.content or ""
        # This content is the reasoning, not the GoalSet — hand it to the format
        # phase. Keep it in the transcript so the formatter can see it.
        messages.append({"role": "assistant", "content": content})
        return await _format_goals(
            client=client,
            model=model,
            messages=messages,
            turn=turn,
            metrics=metrics,
            tool_calls=len(tool_trace),
            finish=_finish,
        )

    return _finish(_EMPTY_GOALS(turn), "empty goals (no reasoning produced / rounds exhausted)")


async def _format_goals(
    *,
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    turn: int,
    metrics: dict[str, Any] | None,
    tool_calls: int,
    finish: Any,
) -> GoalSet:
    """Format phase of the think/format split: serialize the think-phase reasoning
    into a strict GoalSet JSON. No tools, no further deliberation — just the schema.
    """
    from . import agent as agent_module

    messages.append({"role": "user", "content": _FORMAT_PHASE_INSTRUCTION})
    for _ in range(3):
        try:
            response = await agent_module._chat_create(
                client,
                metrics=metrics,
                stage="strategist",
                **_chat_kwargs(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.0,
                    response_format={"type": "text"},
                ),
            )
        except agent_module.TRANSIENT_API_ERRORS as exc:
            logger.warning("Strategist format phase unavailable (%s); empty goals", type(exc).__name__)
            return finish(_EMPTY_GOALS(turn), f"empty goals (split; transient API failure: {type(exc).__name__})")
        except Exception as exc:  # noqa: BLE001
            logger.error("Strategist format phase error: %s; empty goals", exc)
            return finish(_EMPTY_GOALS(turn), f"empty goals (split; API error: {exc})")

        content = response.choices[0].message.content or ""
        goal_set = _parse_goals(content)
        if goal_set is not None:
            return finish(goal_set, f"goals={len(goal_set.goals)} (split; after {tool_calls} tool call(s))")
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": "Your response did not match the GoalSet schema. Return only valid GoalSet JSON.",
        })

    return finish(_EMPTY_GOALS(turn), "empty goals (split; schema never matched)")


def _EMPTY_GOALS(turn: int) -> GoalSet:
    return GoalSet(turn=turn, rationale="fallback: no goals", goals=[])
