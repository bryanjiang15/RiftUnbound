"""Phase-3 search-driving Reasoner.

The Reasoner controls live engine investigation in a bounded ReAct-style loop,
then emits either a verified full-turn line or a GoalSet for TurnSearch.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .prompts import load_prompt
from .schemas import GoalSet, ReasonerEmit
from .strategist import _chat_kwargs, _extract_json_object, _parse_goals, _strip_fences
from .system_prompt import build_system_prompt_from_modules
from .tool_budget import current_budget

logger = logging.getLogger(__name__)

REASONER_MAX_TOOL_ROUNDS = 6
REASONER_TOOL_NAMES = frozenset({
    "evaluate_position",
    "search_turn",
    "search_for",
    "simulate_move",
    "simulate_line",
    "deepen",
    "get_card_detail",
    "lookup_rule",
    "get_keyword",
    "get_opponent_history",
})

_ROLE = load_prompt("reasoner_role_base")
_DISCIPLINE = load_prompt("reasoner_output_discipline_think")
_TASK = load_prompt("reasoner_task")
_FORMAT = load_prompt("reasoner_format_phase")


@dataclass
class _CachedReasoning:
    turn: int
    opp_action_count: int
    emit: ReasonerEmit


class Reasoner:
    def __init__(self) -> None:
        self._cache: dict[str, _CachedReasoning] = {}

    async def reason(
        self,
        *,
        client: AsyncOpenAI,
        model: str,
        game_id: str,
        brief_state: dict[str, Any],
        memory_summary: str = "",
        opponent_action_count: int = 0,
        metrics: dict[str, Any] | None = None,
        known_lines: list[dict[str, Any]] | None = None,
    ) -> tuple[ReasonerEmit, bool]:
        turn = int(brief_state.get("turn_number", 0))
        cached = self._cache.get(game_id)
        if (
            cached
            and cached.turn == turn
            and cached.opp_action_count == opponent_action_count
        ):
            return cached.emit, True
        emit = await _request_reasoning(
            client=client,
            model=model,
            game_id=game_id,
            brief_state=brief_state,
            memory_summary=memory_summary,
            metrics=metrics,
            known_lines=known_lines or [],
        )
        self._cache[game_id] = _CachedReasoning(turn, opponent_action_count, emit)
        return emit, False


def empty_reasoner_emit(turn: int, rationale: str = "fallback: no reasoner result") -> ReasonerEmit:
    return ReasonerEmit(
        kind="goals",
        confidence="goals",
        goal_set=GoalSet(turn=turn, rationale=rationale, goals=[]),
        rationale=rationale,
    )


def _parse_reasoner_emit(content: str, turn: int = 0) -> ReasonerEmit | None:
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
        return None

    goal_set = None
    raw_goals = data.get("goal_set")
    if isinstance(raw_goals, dict):
        goal_set = _parse_goals(json.dumps(raw_goals))
    try:
        return ReasonerEmit(
            schema_version=str(data.get("schema_version", "1.0")),
            kind=str(data.get("kind", "goals")).strip().lower(),
            moves=data.get("moves"),
            chosen_line_id=data.get("chosen_line_id"),
            confidence=str(data.get("confidence", "goals")).strip().lower(),
            goal_set=goal_set,
            rationale=str(data.get("rationale", "")),
        )
    except Exception as exc:
        logger.warning("ReasonerEmit parse failed: %s", exc)
        return None


def _tool_schemas(agent_module: Any) -> list[dict[str, Any]]:
    return [
        tool
        for tool in agent_module.TOOLS
        if tool.get("function", {}).get("name") in REASONER_TOOL_NAMES
    ]


def _remember_lines(result: Any, evidence: dict[str, list[str]]) -> None:
    if not isinstance(result, dict):
        return
    candidates = []
    candidates.extend(result.get("matches", []) or [])
    candidates.extend(result.get("candidate_lines", []) or [])
    candidates.extend(result.get("lines", []) or [])
    for line in candidates:
        if not isinstance(line, dict):
            continue
        moves = [str(m) for m in (line.get("moves", []) or []) if str(m).strip()]
        line_id = str(line.get("line_id", "") or "")
        if moves and line_id:
            evidence[line_id] = moves


def _validated_emit(
    emit: ReasonerEmit,
    *,
    brief_state: dict[str, Any],
    evidence: dict[str, list[str]],
    verified_sequences: set[tuple[str, ...]],
) -> ReasonerEmit:
    """Downgrade unsupported/illegal direct commits to the safe GoalSet path."""
    turn = int(brief_state.get("turn_number", 0))
    if emit.kind != "line" or emit.confidence != "commit":
        if emit.goal_set is None:
            emit.goal_set = GoalSet(turn=turn, rationale=emit.rationale, goals=[])
        emit.kind = "goals"
        emit.confidence = "goals"
        emit.moves = None
        emit.chosen_line_id = None
        return emit

    moves = list(emit.moves or [])
    if emit.chosen_line_id:
        known = evidence.get(emit.chosen_line_id)
        if known is None:
            return empty_reasoner_emit(turn, "fallback: unknown reasoner line id")
        if moves and tuple(moves) != tuple(known):
            return empty_reasoner_emit(turn, "fallback: line id/moves mismatch")
        moves = list(known)
    if not moves or tuple(moves) not in verified_sequences:
        return empty_reasoner_emit(turn, "fallback: line was not engine-confirmed")

    from . import agent as agent_module

    legal = brief_state.get("legal_moves", []) or []
    if not agent_module._command_in_legal_moves(moves[0], legal, brief_state):
        return empty_reasoner_emit(turn, "fallback: reasoner first move is not legal")
    emit.moves = moves
    return emit


async def _request_reasoning(
    *,
    client: AsyncOpenAI,
    model: str,
    game_id: str,
    brief_state: dict[str, Any],
    memory_summary: str,
    metrics: dict[str, Any] | None = None,
    known_lines: list[dict[str, Any]] | None = None,
) -> ReasonerEmit:
    from . import agent as agent_module

    turn = int(brief_state.get("turn_number", 0))
    rules = build_system_prompt_from_modules(
        ["goal_and_role", "core_rules", "keywords_in_play", "goal_vocabulary"],
        brief_state=brief_state,
    )
    system = f"{_ROLE}\n\n{_DISCIPLINE}\n\n{rules}".strip()
    user = (
        f"{_TASK}\n\nRecent timeline:\n{memory_summary or '(none)'}\n\n"
        f"Current state:\n{agent_module._format_brief_state(brief_state)}"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    tool_trace: list[dict[str, Any]] = []
    evidence: dict[str, list[str]] = {}
    verified_sequences: set[tuple[str, ...]] = set()
    _remember_lines({"lines": known_lines or []}, evidence)
    verified_sequences.update(tuple(moves) for moves in evidence.values())
    tools = _tool_schemas(agent_module)
    grounding = "search_turn" if evidence else "evaluate_position"
    reasoning_text = ""

    def finish(emit: ReasonerEmit, outcome: str) -> ReasonerEmit:
        validated = _validated_emit(
            emit,
            brief_state=brief_state,
            evidence=evidence,
            verified_sequences=verified_sequences,
        )
        agent_module._log_tools(
            game_id,
            brief_state,
            tool_trace=tool_trace,
            outcome=outcome,
            stage="reasoner",
            reasoning=reasoning_text,
            final_output=validated.model_dump(exclude_none=True),
        )
        if reasoning_text.strip():
            logger.info(
                "Reasoner recommendation [game=%s turn=%d]:\n%s",
                game_id,
                turn,
                reasoning_text.strip(),
            )
        return validated

    for round_index in range(REASONER_MAX_TOOL_ROUNDS + 1):
        budget = current_budget()
        force_emit = round_index == REASONER_MAX_TOOL_ROUNDS or (
            budget is not None and budget.exhausted
        )
        if round_index == 0:
            tool_choice: Any = {"type": "function", "function": {"name": grounding}}
        elif force_emit:
            tool_choice = "none"
        else:
            tool_choice = "auto"
        try:
            response = await agent_module._chat_create(
                client,
                metrics=metrics,
                stage="reasoner",
                **_chat_kwargs(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=0.1,
                    response_format={"type": "text"},
                ),
            )
        except agent_module.TRANSIENT_API_ERRORS as exc:
            return finish(
                empty_reasoner_emit(turn, f"fallback: transient API failure {type(exc).__name__}"),
                "empty goals (reasoner API unavailable)",
            )
        except Exception as exc:
            logger.error("Reasoner API error: %s", exc)
            return finish(
                empty_reasoner_emit(turn, "fallback: reasoner API error"),
                "empty goals (reasoner API error)",
            )

        msg = response.choices[0].message
        if msg.tool_calls:
            messages.append(msg)  # type: ignore[arg-type]
            for tc in msg.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if name not in REASONER_TOOL_NAMES:
                    result: Any = {"error": f"Tool '{name}' is not available to the Reasoner."}
                    result_text = json.dumps(result)
                else:
                    result_text = agent_module._invoke_traced_tool(
                        tool_trace,
                        round_num=round_index,
                        name=name,
                        args=args,
                    )
                    try:
                        result = json.loads(result_text)
                    except (json.JSONDecodeError, TypeError):
                        result = result_text
                    if (
                        isinstance(result, dict)
                        and "budget_remaining_pct" in result
                        and tool_trace
                    ):
                        tool_trace[-1]["summary"] += (
                            f" | budget {result['budget_remaining_pct']}% remaining"
                        )
                _remember_lines(result, evidence)
                verified_sequences.update(tuple(moves) for moves in evidence.values())
                if (
                    name in {"simulate_line", "simulate_move"}
                    and isinstance(result, dict)
                    and result.get("source") == "live_engine"
                    and result.get("legal") is not False
                    and not result.get("error")
                ):
                    raw_moves = args.get("moves") or [args.get("move", {})]
                    commands = tuple(
                        agent_module.skill_module._move_to_command(move)
                        for move in raw_moves
                    )
                    if commands:
                        verified_sequences.add(commands)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })
            continue

        reasoning_text = msg.content or ""
        messages.append({"role": "assistant", "content": reasoning_text})
        return await _format_emit(
            client=client,
            model=model,
            messages=messages,
            turn=turn,
            metrics=metrics,
            finish=finish,
            tool_calls=len(tool_trace),
        )

    return finish(empty_reasoner_emit(turn), "empty goals (reasoner rounds exhausted)")


async def _format_emit(
    *,
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    turn: int,
    metrics: dict[str, Any] | None,
    finish: Any,
    tool_calls: int,
) -> ReasonerEmit:
    from . import agent as agent_module

    messages.append({"role": "user", "content": _FORMAT})
    for _ in range(3):
        try:
            response = await agent_module._chat_create(
                client,
                metrics=metrics,
                stage="reasoner",
                **_chat_kwargs(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    temperature=0.0,
                    response_format={"type": "text"},
                ),
            )
        except Exception as exc:
            logger.warning("Reasoner format phase failed: %s", exc)
            return finish(empty_reasoner_emit(turn), "empty goals (format failure)")
        content = response.choices[0].message.content or ""
        emit = _parse_reasoner_emit(content, turn=turn)
        if emit is not None:
            return finish(emit, f"emit={emit.kind} after {tool_calls} tool call(s)")
        messages.append({"role": "assistant", "content": content})
        messages.append({
            "role": "user",
            "content": "Return only valid ReasonerEmit JSON matching the requested schema.",
        })
    return finish(empty_reasoner_emit(turn), "empty goals (emit schema never matched)")

