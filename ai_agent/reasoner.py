"""Search-driving Reasoner with request-scoped, engine-verified terminals."""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from openai import AsyncOpenAI
from pydantic import ValidationError

from .investigation_metrics import (
    advisory_critic_notes,
    build_feedback_envelope,
    classify_search_result,
    extract_result_lines,
    has_novel_suffix,
    is_novel_vs_scout,
    rationale_is_score_primary,
)
from .prompts import load_prompt
from .reasoner_context import current_context
from .schemas import GoalSet, ReasonerEmit
from .strategist import _chat_kwargs, _extract_json_object, _strip_fences
from .system_prompt import build_system_prompt_from_modules
from .tool_budget import current_budget

logger = logging.getLogger(__name__)

REASONER_MAX_TOOL_ROUNDS = 6
TERMINAL_RETRIES = 3
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
SEARCH_DRIVING_TOOLS = frozenset({"search_for", "deepen"})
TERMINAL_TOOL_NAMES = frozenset({"commit_line", "emit_goals"})
DEFAULT_SCORE_TIE_BAND = 0.15

_ROLE = load_prompt("reasoner_role_base")
_DISCIPLINE = load_prompt("reasoner_output_discipline_think")
_TASK = load_prompt("reasoner_task")
_FORMAT = load_prompt("reasoner_format_phase")
_FEW_SHOT = load_prompt("reasoner_few_shot_traces")


@dataclass
class _CachedReasoning:
    turn: int
    opp_action_count: int
    root_state_hash: str
    emit: ReasonerEmit
    committed_line: dict[str, Any] | None = None
    telemetry: dict[str, Any] | None = None


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
        root_state_hash: str = "",
    ) -> tuple[ReasonerEmit, bool]:
        turn = int(brief_state.get("turn_number", 0))
        cached = self._cache.get(game_id)
        if (
            cached
            and cached.turn == turn
            and cached.opp_action_count == opponent_action_count
            and cached.root_state_hash == root_state_hash
        ):
            context = current_context()
            if context is not None and cached.committed_line is not None:
                context.registry.restore(cached.committed_line)
            if context is not None and cached.telemetry is not None:
                context.telemetry.update(cached.telemetry)
                context.telemetry["cache_hit"] = True
            return cached.emit, True
        emit = await _request_reasoning(
            client=client,
            model=model,
            game_id=game_id,
            brief_state=brief_state,
            memory_summary=memory_summary,
            metrics=metrics,
            known_lines=known_lines or [],
            root_state_hash=root_state_hash,
        )
        context = current_context()
        committed = (
            context.registry.get(emit.chosen_line_id)
            if context is not None and emit.kind == "line"
            else None
        )
        self._cache[game_id] = _CachedReasoning(
            turn,
            opponent_action_count,
            root_state_hash,
            emit,
            committed,
            dict(context.telemetry) if context is not None else {},
        )
        return emit, False


def base_search_fallback(
    turn: int,
    rationale: str = "base search fallback",
) -> ReasonerEmit:
    return ReasonerEmit(
        kind="base_search_fallback",
        confidence="fallback",
        rationale=rationale,
    )


# Compatibility name retained for callers while empty GoalSets are removed.
def empty_reasoner_emit(turn: int, rationale: str = "fallback: no reasoner result") -> ReasonerEmit:
    return base_search_fallback(turn, rationale)


def _strict_goal_set(raw_goal_set: Any, turn: int) -> tuple[GoalSet | None, str | None]:
    if not isinstance(raw_goal_set, dict):
        return None, "goal_set must be an object"
    normalized = dict(raw_goal_set)
    normalized["turn"] = turn
    raw_goals = normalized.get("goals")
    if not isinstance(raw_goals, list) or not 1 <= len(raw_goals) <= 4:
        return None, "goal_set.goals must contain 1 to 4 goals"
    try:
        goal_set = GoalSet.model_validate(normalized)
    except ValidationError as exc:
        return None, json.dumps(exc.errors(include_url=False), default=str)
    if len(goal_set.goals) != len(raw_goals):
        return None, "every requested goal must validate"
    from .goal_compiler import compile_goals

    overlay = compile_goals(goal_set)
    dropped = [note for note in overlay.notes if note.startswith("drop ")]
    if dropped:
        return None, json.dumps({"goal_errors": dropped})
    return goal_set, None


def _parse_reasoner_emit(content: str, turn: int = 0) -> ReasonerEmit | None:
    """Strict fail-safe parser; native terminal tools are the primary path."""
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
    kind = str(data.get("kind", "")).strip().lower()
    try:
        if kind == "line":
            line_id = str(data.get("chosen_line_id", "") or "")
            if not line_id:
                return None
            return ReasonerEmit(
                kind="line",
                confidence="commit",
                chosen_line_id=line_id,
                rationale=str(data.get("rationale", "")),
            )
        if kind == "goals":
            goal_set, error = _strict_goal_set(data.get("goal_set"), turn)
            if error or goal_set is None:
                return None
            return ReasonerEmit(
                kind="goals",
                confidence="goals",
                goal_set=goal_set,
                rationale=str(data.get("rationale", "")),
            )
    except Exception as exc:
        logger.warning("ReasonerEmit parse failed: %s", exc)
    return None


def _terminal_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "commit_line",
                "description": (
                    "Terminate by committing one COMPLETE engine-registered line. "
                    "Reference its canonical line_id; never copy moves."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "line_id": {"type": "string"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["line_id", "rationale"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "emit_goals",
                "description": (
                    "Terminate with 1-4 strategic goals when tactics remain open. "
                    "The controller sets the current turn."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "goal_set": {
                            "type": "object",
                            "properties": {
                                "schema_version": {"type": "string"},
                                "turn": {"type": "integer"},
                                "rationale": {"type": "string"},
                                "goals": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 4,
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "kind": {
                                                "type": "string",
                                                "enum": [
                                                    "weight_bias",
                                                    "state_target",
                                                    "card_target",
                                                ],
                                            },
                                            "description": {"type": "string"},
                                            "priority": {
                                                "type": "string",
                                                "enum": ["low", "med", "high"],
                                            },
                                            "feature": {"type": "string"},
                                            "multiplier": {"type": "number"},
                                            "metric": {"type": "string"},
                                            "metric_key": {"type": "string"},
                                            "comparator": {
                                                "type": "string",
                                                "enum": [">=", "<=", "=="],
                                            },
                                            "threshold": {"type": "number"},
                                            "card_id": {"type": "string"},
                                        },
                                        "required": ["id", "kind"],
                                    },
                                },
                            },
                            "required": ["goals"],
                        },
                        "rationale": {"type": "string"},
                    },
                    "required": ["goal_set", "rationale"],
                },
            },
        },
    ]


def _tool_schemas(agent_module: Any) -> list[dict[str, Any]]:
    tools = [
        tool
        for tool in agent_module.TOOLS
        if tool.get("function", {}).get("name") in REASONER_TOOL_NAMES
    ]
    return tools + _terminal_tool_schemas()


def _score_tie_band() -> float:
    raw = os.environ.get("RIFTBOUND_SCORE_TIE_BAND", str(DEFAULT_SCORE_TIE_BAND))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return DEFAULT_SCORE_TIE_BAND


def _hide_raw_scores() -> bool:
    return os.environ.get("RIFTBOUND_REASONER_HIDE_RAW_SCORE", "1").strip().lower() not in {
        "0",
        "false",
        "off",
        "no",
    }


def _score_band_label(score: Any, *, band: float) -> str:
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unknown"
    # Quantize into coarse bands so tiny gaps are not decision-looking.
    width = max(band, 0.05)
    bucket = round(value / width) * width
    return f"~{bucket:.2f}±{width:.2f}"


def _strategic_prefix_commands(
    moves: list[Any],
    contexts: list[Any],
    *,
    max_steps: int = 3,
) -> list[str]:
    prefix: list[str] = []
    for index, command in enumerate(moves):
        text = str(command)
        lower = text.strip().lower()
        context = contexts[index] if index < len(contexts) else {}
        kind = str(context.get("kind", "scripted") or "scripted")
        if kind in {"choose", "auto_choice"} or lower.startswith("choose "):
            continue
        if lower in {"pass", "end turn"}:
            continue
        prefix.append(text)
        if len(prefix) >= max_steps:
            break
    return prefix


def _render_resolved_state(resolved: Any) -> dict[str, Any]:
    if not isinstance(resolved, dict):
        return {}
    keep = (
        "wins_game",
        "my_score_after",
        "opponent_score_after",
        "points_scored",
        "my_units_killed",
        "opponent_units_killed",
        "battlefields_controlled",
        "hand_size",
        "ready_runes",
        "energy",
        "power",
    )
    out: dict[str, Any] = {}
    for key in keep:
        if key in resolved:
            out[key] = resolved[key]
    # Preserve compact unknown keys when small.
    if not out:
        for key, value in list(resolved.items())[:8]:
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[str(key)] = value
    return out


def _render_scout_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    hide_scores = _hide_raw_scores()
    band = _score_tie_band()
    for line in lines:
        moves = list(line.get("moves", []) or [])
        contexts = list(line.get("move_contexts", []) or [])
        steps = []
        for index, command in enumerate(moves):
            context = contexts[index] if index < len(contexts) else {}
            step = {
                "command": command,
                "kind": context.get("kind", "scripted"),
                "prefix_steps": index + 1,
            }
            if context.get("context"):
                step["context"] = context["context"]
            steps.append(step)
        breakdown = line.get("score_breakdown", {}) or {}
        drivers = sorted(
            (
                (str(key), float(value))
                for key, value in breakdown.items()
                if isinstance(value, (int, float))
            ),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:4]
        entry: dict[str, Any] = {
            "line_id": line.get("line_id"),
            "steps": steps,
            "strategic_prefix_moves": _strategic_prefix_commands(moves, contexts),
            "deepen_hint": {
                "line_id": line.get("line_id"),
                "prefix_steps_options": list(
                    range(1, min(4, max(1, len(moves))))
                ),
            },
            "score_band": _score_band_label(line.get("score", 0.0), band=band),
            "top_score_terms": dict(drivers),
            "resolved_state": _render_resolved_state(line.get("resolved_state")),
            "complete": bool(line.get("complete")),
            "terminal_reason": line.get("terminal_reason", ""),
            "contested": bool(line.get("opponent_windows")),
            "opponent_windows": len(line.get("opponent_windows", []) or []),
            "root_state_hash": line.get("root_state_hash", ""),
        }
        if not hide_scores:
            entry["score"] = line.get("score", 0.0)
        rendered.append(entry)
    return rendered


def _investigation_exemption(
    brief_state: dict[str, Any],
    known_lines: list[dict[str, Any]],
) -> str | None:
    legal = list(brief_state.get("legal_moves", []) or [])
    if len(legal) <= 1:
        return "forced"
    complete = [line for line in known_lines if line.get("complete")]
    if len(complete) == 1 and len(known_lines) <= 1:
        return "single_playable_line"
    budget = current_budget()
    if budget is not None and budget.exhausted:
        return "budget_exhausted"
    return None


def _successful_search(name: str, result: Any) -> bool:
    """Non-empty live engine result (may still be a scout duplicate)."""
    if name not in SEARCH_DRIVING_TOOLS or not isinstance(result, dict):
        return False
    if result.get("error") or result.get("legal") is False:
        return False
    if result.get("source") != "live_engine":
        return False
    return bool(extract_result_lines(name, result))


def _novel_search(
    name: str,
    result: Any,
    scout_leader: tuple[str, ...],
) -> bool:
    if not _successful_search(name, result):
        return False
    return is_novel_vs_scout(name, result, scout_leader)


def _engine_unavailable(result: Any) -> bool:
    return isinstance(result, dict) and str(result.get("source", "")) in {
        "unavailable",
        "presim_corpus",
    }


def _resolved_delta_summary(lines: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for line in lines[:3]:
        line_id = line.get("line_id", "?")
        resolved = _render_resolved_state(line.get("resolved_state"))
        if resolved:
            chunks.append(f"{line_id}:{resolved}")
        else:
            chunks.append(f"{line_id}:(no resolved_state)")
    return "; ".join(chunks)


def _terminal_emit(
    name: str,
    args: dict[str, Any],
    *,
    turn: int,
    root_state_hash: str,
    investigation_satisfied: bool,
    exemption: str | None,
    comparison_required: bool,
) -> tuple[ReasonerEmit | None, str | None]:
    context = current_context()
    if context is None:
        return None, "Reasoner request context is unavailable"
    if not investigation_satisfied and exemption is None:
        return None, (
            "Before terminating, make one successful novel search_for or deepen "
            "call (a scout-duplicate result does not satisfy this gate). "
            "An empty or failed call does not count."
        )
    rationale = str(args.get("rationale", "")).strip()
    if not rationale:
        return None, "rationale must be non-empty"
    if comparison_required and "scout" not in rationale.lower():
        return None, (
            "A distinct alternative was found. Compare it with the scout leader "
            "explicitly in rationale before terminating."
        )
    if comparison_required and rationale_is_score_primary(rationale):
        return None, (
            "Score-only rationale rejected while a distinct alternative remains. "
            "Compare concrete resulting-state deltas (points, board, resources, "
            f"windows); scores may break ties only inside band {_score_tie_band()}."
        )
    if name == "emit_goals":
        goal_set, error = _strict_goal_set(args.get("goal_set"), turn)
        if error or goal_set is None:
            return None, error or "invalid goal_set"
        return ReasonerEmit(
            kind="goals",
            confidence="goals",
            goal_set=goal_set,
            rationale=rationale,
        ), None
    if name != "commit_line":
        return None, f"unknown terminal tool {name}"
    line_id = str(args.get("line_id", "") or "")
    line = context.registry.get(line_id)
    if line is None:
        return None, f"unknown registry line_id '{line_id}'"
    if not line.get("legal", True):
        return None, f"line '{line_id}' is marked illegal"
    if not line.get("complete", False):
        return None, (
            f"line '{line_id}' is incomplete "
            f"({line.get('terminal_reason', 'unknown terminal reason')})"
        )
    if not root_state_hash or line.get("root_state_hash") != root_state_hash:
        return None, f"line '{line_id}' does not match the pinned root state"
    moves = list(line.get("moves", []) or [])
    contexts = list(line.get("move_contexts", []) or [])
    hashes = list(line.get("expected_pre_hashes", []) or [])
    if not moves or len(moves) != len(contexts) or len(moves) != len(hashes):
        return None, f"line '{line_id}' lacks parallel executable metadata"
    if any(not str(value) for value in hashes):
        return None, f"line '{line_id}' contains an empty pre-step hash"
    return ReasonerEmit(
        kind="line",
        confidence="commit",
        chosen_line_id=line_id,
        rationale=rationale,
    ), None


def _validated_emit(
    emit: ReasonerEmit,
    *,
    brief_state: dict[str, Any],
) -> ReasonerEmit:
    """Compatibility wrapper around registry-only terminal validation."""
    turn = int(brief_state.get("turn_number", 0))
    context = current_context()
    if context is None:
        return base_search_fallback(turn, "fallback: no request registry")
    if emit.kind == "goals" and emit.goal_set is not None and emit.goal_set.goals:
        emit.goal_set.turn = turn
        return emit
    if emit.kind == "line" and emit.chosen_line_id:
        line = context.registry.get(emit.chosen_line_id)
        if line and line.get("complete") and line.get("legal", True):
            return emit
    return base_search_fallback(turn, "fallback: terminal validation failed")


async def _request_reasoning(
    *,
    client: AsyncOpenAI,
    model: str,
    game_id: str,
    brief_state: dict[str, Any],
    memory_summary: str,
    metrics: dict[str, Any] | None = None,
    known_lines: list[dict[str, Any]] | None = None,
    root_state_hash: str = "",
) -> ReasonerEmit:
    from . import agent as agent_module

    known_lines = known_lines or []
    started_at = time.monotonic()
    turn = int(brief_state.get("turn_number", 0))
    context = current_context()
    rules = build_system_prompt_from_modules(
        ["goal_and_role", "core_rules", "keywords_in_play", "goal_vocabulary"],
        brief_state=brief_state,
    )
    system = f"{_ROLE}\n\n{_DISCIPLINE}\n\n{_FEW_SHOT}\n\n{rules}".strip()
    scout_block = (
        json.dumps(_render_scout_lines(known_lines), indent=2, default=str)
        if known_lines
        else "(none)"
    )
    user = (
        f"{_TASK}\n\nRecent timeline:\n{memory_summary or '(none)'}\n\n"
        f"Current state:\n{agent_module._format_brief_state(brief_state)}\n\n"
        f"PINNED ROOT HASH: {root_state_hash or '(unavailable)'}\n\n"
        "SCOUT BASELINE (already grounded; do not call search_turn merely to reread it):\n"
        f"{scout_block}"
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    tools = _tool_schemas(agent_module)
    tool_trace: list[dict[str, Any]] = []
    reasoning_text = ""
    terminal_errors: list[str] = []
    exemption = _investigation_exemption(brief_state, known_lines)
    investigation_satisfied = False
    novel_investigation = False
    comparison_required = False
    local_fork_attempted = False
    novel_suffix_found = False
    failed_search_calls = 0
    recovered_failed_searches = 0
    pending_failure = False
    seen_queries: set[str] = set()
    last_result_status = ""
    scout_leader = tuple(str(m) for m in (known_lines[0].get("moves", []) or [])) if known_lines else ()

    if context is not None:
        context.telemetry.update({
            "investigation_exemption": exemption,
            "scout_line_count": len(known_lines),
            "root_state_hash": root_state_hash,
            "successful_search_tools": [],
            "terminal_validation_errors": terminal_errors,
            "failed_search_calls": 0,
            "recovered_failed_searches": 0,
            "novel_investigation": False,
            "local_fork_attempted": False,
            "novel_suffix_found": False,
        })

    def finish(emit: ReasonerEmit, outcome: str) -> ReasonerEmit:
        if context is not None:
            total_latency_ms = int((time.monotonic() - started_at) * 1000)
            active_budget = current_budget()
            engine_latency_ms = (
                active_budget.engine_time_ms if active_budget is not None else 0
            )
            registry_lines = context.registry.lines()
            complete_lengths = [
                len(line.get("moves", []) or [])
                for line in registry_lines
                if line.get("complete")
            ]
            selected_line = context.registry.get(emit.chosen_line_id)
            context.telemetry.update({
                "terminal_kind": emit.kind,
                "valid_goal_count": (
                    len(emit.goal_set.goals) if emit.goal_set is not None else 0
                ),
                "investigation_satisfied": investigation_satisfied,
                "novel_investigation": novel_investigation,
                "local_fork_attempted": local_fork_attempted,
                "novel_suffix_found": novel_suffix_found,
                "failed_search_calls": failed_search_calls,
                "recovered_failed_searches": recovered_failed_searches,
                "comparison_required": comparison_required,
                "score_primary_rationale": rationale_is_score_primary(emit.rationale),
                "tool_mix": [entry.get("name") for entry in tool_trace],
                "budget": active_budget.status() if active_budget else {},
                "scout_agreement": bool(
                    emit.kind == "line"
                    and known_lines
                    and emit.chosen_line_id == known_lines[0].get("line_id")
                ),
                "selected_source_lineage": (
                    selected_line.get("source_lineage", [])
                    if selected_line is not None
                    else []
                ),
                "unique_sequence_count": context.registry.unique_sequence_count,
                "max_complete_line_length": max(complete_lengths, default=0),
                "engine_latency_ms": engine_latency_ms,
                "model_orchestration_latency_ms": max(
                    0, total_latency_ms - engine_latency_ms
                ),
                "reasoner_latency_ms": total_latency_ms,
                "fallback_reason": (
                    emit.rationale if emit.kind == "base_search_fallback" else ""
                ),
            })
        agent_module._log_tools(
            game_id,
            brief_state,
            tool_trace=tool_trace,
            outcome=outcome,
            stage="reasoner",
            reasoning=reasoning_text,
            final_output={
                **emit.model_dump(exclude_none=True),
                "telemetry": dict(context.telemetry) if context is not None else {},
            },
        )
        return emit

    terminal_failures = 0
    for round_index in range(REASONER_MAX_TOOL_ROUNDS + 1):
        budget = current_budget()
        force_terminal = round_index == REASONER_MAX_TOOL_ROUNDS or (
            budget is not None and budget.exhausted
        )
        if round_index == 0 and not known_lines:
            tool_choice: Any = {
                "type": "function",
                "function": {"name": "evaluate_position"},
            }
        elif force_terminal:
            tool_choice = "auto"
            messages.append({
                "role": "user",
                "content": (
                    "Tool/round budget is ending. Call commit_line or emit_goals now. "
                    "If the investigation gate is exempt, use the best safe terminal."
                ),
            })
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
                base_search_fallback(
                    turn, f"fallback: transient API failure {type(exc).__name__}"
                ),
                "base_search_fallback (reasoner API unavailable)",
            )
        except Exception as exc:
            logger.error("Reasoner API error: %s", exc)
            return finish(
                base_search_fallback(turn, "fallback: reasoner API error"),
                "base_search_fallback (reasoner API error)",
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
                if name in TERMINAL_TOOL_NAMES:
                    active_budget = current_budget()
                    if (
                        not investigation_satisfied
                        and exemption is None
                        and active_budget is not None
                        and active_budget.exhausted
                    ):
                        exemption = "budget_exhausted"
                        if context is not None:
                            context.telemetry["investigation_exemption"] = exemption
                    emit, error = _terminal_emit(
                        name,
                        args,
                        turn=turn,
                        root_state_hash=root_state_hash,
                        investigation_satisfied=investigation_satisfied,
                        exemption=exemption,
                        comparison_required=comparison_required,
                    )
                    if error is None and emit is not None:
                        tool_trace.append({
                            "round": round_index,
                            "name": name,
                            "args": args,
                            "summary": f"accepted terminal={emit.kind}",
                        })
                        return finish(emit, f"terminal={emit.kind}")
                    terminal_failures += 1
                    terminal_errors.append(str(error))
                    result: Any = {
                        "accepted": False,
                        "error": error,
                        "terminal_retries_remaining": max(
                            0, TERMINAL_RETRIES - terminal_failures
                        ),
                    }
                    tool_trace.append({
                        "round": round_index,
                        "name": name,
                        "args": args,
                        "summary": f"rejected: {error}",
                    })
                    result_text = json.dumps(result)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })
                    if terminal_failures >= TERMINAL_RETRIES:
                        return finish(
                            base_search_fallback(
                                turn, "fallback: terminal retry budget exhausted"
                            ),
                            "base_search_fallback (terminal retries exhausted)",
                        )
                    continue

                if name not in REASONER_TOOL_NAMES:
                    result = {"error": f"Tool '{name}' is not available to the Reasoner."}
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

                    envelope = ""
                    if name in SEARCH_DRIVING_TOOLS and isinstance(result, dict):
                        status = classify_search_result(name, result, scout_leader)
                        last_result_status = status
                        result["result_status"] = status
                        query_key = json.dumps(
                            {"name": name, "args": args},
                            sort_keys=True,
                            default=str,
                        )
                        is_repeat = query_key in seen_queries
                        seen_queries.add(query_key)
                        prefix_steps = int(args.get("prefix_steps") or 0)
                        if name == "deepen" and (
                            prefix_steps > 0 or bool(args.get("moves"))
                        ):
                            local_fork_attempted = True
                        if has_novel_suffix(
                            name, result, scout_leader, prefix_steps or 1
                        ):
                            novel_suffix_found = True

                        lines = extract_result_lines(name, result)
                        distinct = bool(
                            scout_leader
                            and any(
                                tuple(str(m) for m in (line.get("moves", []) or []))
                                != scout_leader
                                for line in lines
                            )
                        )
                        # Preserve comparison_required across rounds (logical OR).
                        comparison_required = comparison_required or distinct

                        if status in {"illegal_seed", "empty", "unavailable"}:
                            failed_search_calls += 1
                            pending_failure = True
                        elif _novel_search(name, result, scout_leader):
                            novel_investigation = True
                            investigation_satisfied = True
                            if pending_failure:
                                recovered_failed_searches += 1
                                pending_failure = False
                            if context is not None:
                                context.telemetry["successful_search_tools"].append(name)
                                context.telemetry["alternative_query"] = args
                        elif status == "duplicate":
                            # Explicitly do not satisfy the novelty gate.
                            if context is not None:
                                context.telemetry.setdefault(
                                    "duplicate_search_tools", []
                                ).append(name)

                        if name in SEARCH_DRIVING_TOOLS and _engine_unavailable(result):
                            exemption = "engine_unavailable"
                            if context is not None:
                                context.telemetry["investigation_exemption"] = exemption

                        critic = advisory_critic_notes(
                            novel_investigation=novel_investigation,
                            local_fork_attempted=local_fork_attempted,
                            failed_queries=failed_search_calls,
                            recovered_failures=recovered_failed_searches,
                            result_status=status,
                            comparison_required=comparison_required,
                        )
                        branch = (
                            "switch_frontier"
                            if status in {"duplicate", "illegal_seed", "empty"}
                            else "continue_current"
                        )
                        envelope = build_feedback_envelope(
                            previous_query={"tool": name, **args},
                            result_status=status,
                            engine_state_delta=_resolved_delta_summary(lines),
                            opponent_windows=sum(
                                len(line.get("opponent_windows", []) or [])
                                for line in lines
                            ),
                            tool_error=str(result.get("error", "") or ""),
                            is_repeat=is_repeat,
                            forward_progress=novel_investigation or distinct,
                            branch_control=branch,
                            revised_hypothesis=(
                                "; ".join(critic) if critic else ""
                            ),
                        )
                        if result.get("suggested_prefix") is not None:
                            envelope += (
                                f"SUGGESTED PREFIX: {result.get('suggested_prefix')}\n"
                            )
                        result_text = json.dumps(result)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_text,
                    })
                    if envelope:
                        messages.append({
                            "role": "user",
                            "content": envelope,
                        })
                    if context is not None:
                        context.telemetry.update({
                            "failed_search_calls": failed_search_calls,
                            "recovered_failed_searches": recovered_failed_searches,
                            "novel_investigation": novel_investigation,
                            "local_fork_attempted": local_fork_attempted,
                            "novel_suffix_found": novel_suffix_found,
                            "last_result_status": last_result_status,
                            "comparison_required": comparison_required,
                        })
                    continue
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })
            continue

        reasoning_text = msg.content or ""
        messages.append({"role": "assistant", "content": reasoning_text})
        if terminal_failures < TERMINAL_RETRIES:
            terminal_failures += 1
            messages.append({
                "role": "user",
                "content": (
                    "Do not end in prose. Call commit_line(line_id, rationale) or "
                    "emit_goals(goal_set, rationale). Empty goals are invalid."
                ),
            })
            continue
        break

    emit = await _format_emit(
        client=client,
        model=model,
        messages=messages,
        turn=turn,
        metrics=metrics,
    )
    if emit is not None:
        args = (
            {"line_id": emit.chosen_line_id, "rationale": emit.rationale}
            if emit.kind == "line"
            else {
                "goal_set": emit.goal_set.model_dump() if emit.goal_set else None,
                "rationale": emit.rationale,
            }
        )
        checked, error = _terminal_emit(
            "commit_line" if emit.kind == "line" else "emit_goals",
            args,
            turn=turn,
            root_state_hash=root_state_hash,
            investigation_satisfied=investigation_satisfied,
            exemption=exemption,
            comparison_required=comparison_required,
        )
        if checked is not None and error is None:
            return finish(checked, f"fail-safe format terminal={checked.kind}")
        terminal_errors.append(str(error))
    return finish(
        base_search_fallback(turn, "fallback: no valid terminal decision"),
        "base_search_fallback (no valid terminal)",
    )


async def _format_emit(
    *,
    client: AsyncOpenAI,
    model: str,
    messages: list[dict[str, Any]],
    turn: int,
    metrics: dict[str, Any] | None,
    finish: Callable[..., Any] | None = None,
    tool_calls: int = 0,
) -> ReasonerEmit | None:
    """One-shot prose-to-JSON fail-safe; it never overrides a native terminal."""
    from . import agent as agent_module

    messages.append({"role": "user", "content": _FORMAT})
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
        logger.warning("Reasoner fail-safe format phase failed: %s", exc)
        return None
    return _parse_reasoner_emit(
        response.choices[0].message.content or "",
        turn=turn,
    )
