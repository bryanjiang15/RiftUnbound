"""
Riftbound AI Agent — shared SQL capture helpers.

The tuning-dataset writes were historically inlined in the FastAPI endpoints of
``main.py``. They are factored out here so the EXACT same code path persists a
decision/game whether it arrives over HTTP (live play / online self-play) or is
replayed from a capture log after an offline self-play run
(``import_selfplay_logs.py``). Keeping a single implementation is what makes the
offline path provably equivalent to the live one.

Every function operates on a ``Memory`` instance plus plain dicts / pydantic
models — no FastAPI globals — so the importer can call them directly.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from .goal_compiler import ProfileOverlay, goal_achievement_for_line
from .memory import Memory
from .schemas import CandidateLine, Decision, DecisionRequest, GoalSet, Move, SearchStats

logger = logging.getLogger(__name__)

# Maps a request's scoring-profile JSON to its weight_versions.id (per-seat
# attribution). The server and the importer each supply their own resolver.
WeightResolver = Callable[[Optional[str]], Optional[int]]


# ── Tuning dataset capture ────────────────────────────────────────────────────


def snapshot_scalars(brief_state: dict) -> dict:
    """Extract the fast-filter scalar columns from a BriefState dict."""
    my_units = brief_state.get("my_base_units", []) or []
    opp_units = brief_state.get("opponent_base_units", []) or []
    battlefields = brief_state.get("battlefields", []) or []
    my_index = brief_state.get("my_player_index", 0)

    def _might(units: list) -> int:
        return sum(int(u.get("current_might", 0) or 0) for u in units if isinstance(u, dict))

    # Battlefield units also carry might; include them in the board-might diff.
    my_bf_might = 0
    opp_bf_might = 0
    bf_control_net = 0
    for bf in battlefields:
        if not isinstance(bf, dict):
            continue
        my_bf_might += _might(bf.get("my_units", []) or [])
        opp_bf_might += _might(bf.get("opponent_units", []) or [])
        controller = bf.get("controller_index", -1)
        if controller == my_index:
            bf_control_net += 1
        elif controller >= 0:
            bf_control_net -= 1

    board_might_diff = (_might(my_units) + my_bf_might) - (_might(opp_units) + opp_bf_might)
    runes = brief_state.get("my_runes", []) or []
    ready_runes = 0
    for rune in runes:
        if isinstance(rune, dict) and not rune.get("is_exhausted", False):
            ready_runes += 1
    return {
        "my_score": brief_state.get("my_score"),
        "opp_score": brief_state.get("opponent_score"),
        "my_energy": brief_state.get("my_energy"),
        "board_might_diff": board_might_diff,
        "cards_in_hand": len(brief_state.get("my_hand", []) or []),
        "cards_in_hand_opp": brief_state.get("opponent_hand_size"),
        "bf_control_net": bf_control_net,
        "my_rune_count": len(runes),
        "my_ready_rune_count": ready_runes,
    }


def _serialize_moves(moves: list) -> list:
    """Render a candidate line's moves to a JSON-safe list."""
    out = []
    for m in moves:
        if hasattr(m, "model_dump"):
            out.append(m.model_dump())
        else:
            out.append(m)
    return out


def _move_strings(moves: list) -> list[str]:
    """Flatten candidate moves to command strings for goal/card matching."""
    out: list[str] = []
    for m in moves or []:
        if isinstance(m, str):
            out.append(m)
        elif isinstance(m, dict):
            cmd = m.get("command") or m.get("to_command")
            if cmd:
                out.append(str(cmd))
            else:
                out.append(json_dumps_safe(m))
        elif hasattr(m, "to_command"):
            try:
                out.append(str(m.to_command()))
                continue
            except Exception:
                pass
            if hasattr(m, "model_dump"):
                out.append(json_dumps_safe(m.model_dump()))
            else:
                out.append(str(m))
        else:
            out.append(str(m))
    return out


def json_dumps_safe(value: Any) -> str:
    try:
        return json.dumps(value, default=str, sort_keys=True)
    except Exception:
        return str(value)


def _goal_telemetry(
    *,
    goals_source: Optional[str],
    goal_set: Optional[GoalSet],
    overlay: Optional[ProfileOverlay],
    chosen: Any,
) -> dict[str, Any]:
    """Build the GoalSet/overlay fields for a search_decisions row."""
    source = goals_source or "none"
    goal_set_dict = None
    overlay_dict = None
    chosen_delta = None
    achieved = None

    if goal_set is not None:
        goal_set_dict = (
            goal_set.model_dump() if hasattr(goal_set, "model_dump") else goal_set
        )
    effective_overlay = overlay if overlay is not None else ProfileOverlay()
    if not effective_overlay.is_empty():
        overlay_dict = effective_overlay.to_dict()
    # Always record per-goal achievement when a GoalSet is present, even if the
    # compiled overlay is empty (all goals dropped) — leaf met/satisfaction still
    # evaluates from Goal fields / features.
    if goal_set is not None and chosen is not None:
        features = getattr(chosen, "features", None) or {}
        breakdown = getattr(chosen, "score_breakdown", None) or {}
        moves = _move_strings(getattr(chosen, "moves", None) or [])
        chosen_delta, achieved = goal_achievement_for_line(
            goal_set,
            effective_overlay,
            features=features,
            score_breakdown=breakdown,
            moves=moves,
        )
    elif source == "none" and goal_set is None and overlay is None:
        source = "none"

    if source not in ("strategist", "reasoner", "none"):
        source = "none"

    return {
        "goals_source": source,
        "goal_set": goal_set_dict,
        "overlay": overlay_dict,
        "chosen_overlay_delta": chosen_delta,
        "chosen_goal_achieved": achieved,
    }


def capture_search_decision(
    *,
    memory: Memory,
    game_id: str,
    decision_index: int,
    brief_state: dict,
    request: DecisionRequest,
    decision: Decision,
    origin: str,
    weight_resolver: WeightResolver,
    goals_source: Optional[str] = None,
    goal_set: Optional[GoalSet] = None,
    overlay: Optional[ProfileOverlay] = None,
) -> None:
    """Persist the search_decisions / candidate_lines / decision_snapshots rows."""
    candidates = list(request.candidate_lines or [])
    if not candidates:
        return
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    best_score = ranked[0].score
    second_score = ranked[1].score if len(ranked) > 1 else None
    score_margin = (best_score - second_score) if second_score is not None else None

    chosen = None
    if decision.chosen_line_id:
        chosen = next((c for c in candidates if c.line_id == decision.chosen_line_id), None)
    chosen_score = chosen.score if chosen is not None else None
    regret = (best_score - chosen_score) if chosen_score is not None else None

    cand_rows = []
    for rank, c in enumerate(ranked):
        cand_rows.append(
            {
                "line_id": c.line_id,
                "rank": rank,
                "score": c.score,
                "chosen": bool(chosen is not None and c.line_id == chosen.line_id),
                "moves": _serialize_moves(c.moves),
                "breakdown": c.score_breakdown,
                "features": c.features,
                "resolved_state": c.resolved_state,
                "search_state": c.search_state,
            }
        )

    turn = brief_state.get("turn_number", 0)
    decision_type = brief_state.get("decision_type", "unknown")
    mode = request.search_stats.mode if request.search_stats else "main"
    # Attribute this row to the seat's actual profile (per-seat), not the single
    # profile the server read at startup.
    weight_version_id = weight_resolver(request.scoring_profile_json)
    goal_fields = _goal_telemetry(
        goals_source=goals_source,
        goal_set=goal_set,
        overlay=overlay,
        chosen=chosen,
    )

    memory.record_search_decision(
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        decision_type=decision_type,
        mode=mode,
        my_player_index=brief_state.get("my_player_index"),
        chosen_line_id=decision.chosen_line_id,
        chosen_line_score=chosen_score,
        best_candidate_score=best_score,
        regret=regret,
        score_margin=score_margin,
        num_candidates=len(candidates),
        chosen_breakdown=(chosen.score_breakdown if chosen is not None else None),
        chosen_features=(chosen.features if chosen is not None else None),
        search_stats=(request.search_stats.model_dump() if request.search_stats else None),
        selector_source=decision.selector_source,
        selector_reasoning=decision.reasoning,
        origin=origin,
        weight_version_id=weight_version_id,
        candidates=cand_rows,
        goals_source=goal_fields["goals_source"],
        goal_set=goal_fields["goal_set"],
        overlay=goal_fields["overlay"],
        chosen_overlay_delta=goal_fields["chosen_overlay_delta"],
        chosen_goal_achieved=goal_fields["chosen_goal_achieved"],
    )
    analysis_state = request.analysis_state_json
    if isinstance(analysis_state, str) and analysis_state.strip():
        try:
            analysis_state = json.loads(analysis_state)
        except Exception:
            pass
    memory.record_decision_snapshot(
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        scalars=snapshot_scalars(brief_state),
        brief_state=brief_state,
        analysis_state=analysis_state if analysis_state else None,
        analysis_state_schema_version=request.analysis_state_schema_version,
        root_state_hash=request.root_state_hash,
    )


def capture_decision(
    *,
    memory: Memory,
    brief_state: dict,
    request: DecisionRequest,
    decision: Decision,
    eval_metrics: dict,
    search_enabled: bool,
    data_origin: str,
    capture_seat: Optional[int],
    weight_resolver: WeightResolver,
    goals_source: Optional[str] = None,
    goal_set: Optional[GoalSet] = None,
    overlay: Optional[ProfileOverlay] = None,
) -> None:
    """Persist all rows for one produced decision (episodic + eval + tuning).

    Mirrors the side effects of the ``/decision`` endpoint so the live HTTP path
    and the offline importer write identical data. ``decision`` must already be
    computed (argmax / selector) by the caller.
    """
    game_id = request.game_id

    # Record in episodic memory (accepted status unknown until Godot responds).
    try:
        memory.record(
            game_id=game_id,
            turn=brief_state.get("turn_number", 0),
            decision_type=brief_state.get("decision_type", "unknown"),
            brief_state=brief_state,
            reasoning=decision.reasoning,
            move=decision.move.model_dump(),
        )
    except Exception as exc:
        logger.warning("Memory record failed: %s", exc)

    # Record server-side reliability metrics for this decision (eval track).
    try:
        decision_index = memory._decision_counters.get(game_id, 0) - 1
        memory.record_decision_metrics(
            game_id=game_id,
            turn=brief_state.get("turn_number", 0),
            decision_index=decision_index,
            decision_type=brief_state.get("decision_type", "unknown"),
            metrics=eval_metrics,
        )
    except Exception as exc:
        logger.warning("Decision metrics record failed: %s", exc)

    # Capture the tuning dataset row when this decision came from the engine
    # search. When a capture-seat filter is active, store only that seat's rows.
    capture_ok = capture_seat is None or brief_state.get("my_player_index") == capture_seat
    if search_enabled and request.candidate_lines and capture_ok:
        try:
            decision_index = memory._decision_counters.get(game_id, 0) - 1
            capture_search_decision(
                memory=memory,
                game_id=game_id,
                decision_index=decision_index,
                brief_state=brief_state,
                request=request,
                decision=decision,
                origin=data_origin,
                weight_resolver=weight_resolver,
                goals_source=goals_source,
                goal_set=goal_set,
                overlay=overlay,
            )
        except Exception as exc:
            logger.warning("Search decision capture failed: %s", exc)


def compact_tool_trace(tool_trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Shrink a Reasoner tool trace for SQL/eval (no full result bodies)."""
    out: list[dict[str, Any]] = []
    for entry in tool_trace or []:
        args = entry.get("args") or {}
        compact_args: dict[str, Any] = {}
        if isinstance(args, dict):
            for key, value in list(args.items())[:8]:
                if isinstance(value, (str, int, float, bool)) or value is None:
                    compact_args[key] = (
                        value if not isinstance(value, str) or len(value) <= 80
                        else value[:77] + "..."
                    )
                else:
                    rendered = json_dumps_safe(value)
                    compact_args[key] = (
                        rendered if len(rendered) <= 80 else rendered[:77] + "..."
                    )
        summary = entry.get("summary") or ""
        if isinstance(summary, str) and len(summary) > 200:
            summary = summary[:197] + "..."
        out.append(
            {
                "round": entry.get("round"),
                "name": entry.get("name"),
                "args": compact_args,
                "result_status": entry.get("result_status"),
                "summary": summary,
            }
        )
    return out


def _candidate_from_committed(committed_line: dict[str, Any]) -> CandidateLine:
    """Build a CandidateLine from a reasoner registry committed_line dict."""
    moves = list(committed_line.get("moves") or [])
    return CandidateLine(
        line_id=str(committed_line.get("line_id") or "reasoner-line"),
        moves=moves,
        move_contexts=list(committed_line.get("move_contexts") or []),
        expected_pre_hashes=list(committed_line.get("expected_pre_hashes") or []),
        score=float(committed_line.get("score") or 0.0),
        score_breakdown=dict(committed_line.get("score_breakdown") or {}),
        features=dict(committed_line.get("features") or {}),
        resolved_state=dict(committed_line.get("resolved_state") or {}),
        search_state=dict(committed_line.get("search_state") or {}),
        root_state_hash=str(committed_line.get("root_state_hash") or ""),
        legal=bool(committed_line.get("legal", True)),
        complete=bool(committed_line.get("complete", False)),
        terminal_reason=str(committed_line.get("terminal_reason") or ""),
        search_mode=str(committed_line.get("search_mode") or "main"),
    )


def capture_reasoner_line_decision(
    *,
    memory: Memory,
    brief_state: dict,
    request: Any,
    committed_line: dict[str, Any],
    rationale: Optional[str],
    eval_metrics: dict,
    search_enabled: bool,
    data_origin: str,
    capture_seat: Optional[int],
    weight_resolver: WeightResolver,
) -> Optional[int]:
    """Persist episodic + snapshot + search rows for a reasoner-committed line.

    Reasoner ``kind=line`` commits skip ``/decision`` on the Godot side, so this
    mirrors ``capture_decision`` using the committed registry line as the chosen
    candidate. Returns the allocated ``decision_index``, or None on skip/failure.
    """
    from .agent import _move_from_command

    moves = list(committed_line.get("moves") or [])
    if not moves:
        return None
    first_cmd = str(moves[0])
    move = _move_from_command(first_cmd) or Move(action="pass")
    chosen_line_id = str(
        committed_line.get("line_id")
        or getattr(request, "chosen_line_id", None)
        or "reasoner-line"
    )
    decision = Decision(
        reasoning=rationale or "Reasoner committed line.",
        move=move,
        chosen_line_id=chosen_line_id,
        selector_source="reasoner",
    )

    scout = list(getattr(request, "candidate_lines", None) or [])
    committed_cand = _candidate_from_committed(committed_line)
    if committed_cand.line_id and not any(
        getattr(c, "line_id", None) == committed_cand.line_id for c in scout
    ):
        candidates = list(scout) + [committed_cand]
    else:
        # Replace scout copy with the full committed registry entry when ids match.
        candidates = []
        replaced = False
        for c in scout:
            if getattr(c, "line_id", None) == committed_cand.line_id:
                candidates.append(committed_cand)
                replaced = True
            else:
                candidates.append(c)
        if not replaced:
            candidates.append(committed_cand)

    search_stats = getattr(request, "search_stats", None) or SearchStats(
        mode=str(committed_line.get("search_mode") or "main")
    )
    root_hash = (
        getattr(request, "root_state_hash", None)
        or committed_line.get("root_state_hash")
        or ""
    )
    decision_request = DecisionRequest(
        brief_state=getattr(request, "brief_state"),
        game_id=getattr(request, "game_id"),
        candidate_lines=candidates,
        search_stats=search_stats,
        scoring_profile_json=getattr(request, "scoring_profile_json", None),
        analysis_state_json=getattr(request, "analysis_state_json", None),
        analysis_state_schema_version=getattr(
            request, "analysis_state_schema_version", None
        ),
        root_state_hash=root_hash or None,
    )

    try:
        capture_decision(
            memory=memory,
            brief_state=brief_state,
            request=decision_request,
            decision=decision,
            eval_metrics=eval_metrics,
            search_enabled=search_enabled,
            data_origin=data_origin,
            capture_seat=capture_seat,
            weight_resolver=weight_resolver,
            goals_source="reasoner",
            goal_set=None,
            overlay=None,
        )
    except Exception as exc:
        logger.warning("Reasoner line decision capture failed: %s", exc)
        return None

    game_id = getattr(request, "game_id", "")
    return memory._decision_counters.get(game_id, 0) - 1


def capture_reasoner_decision(
    *,
    memory: Memory,
    game_id: str,
    turn: int,
    decision_index: Optional[int],
    root_state_hash: Optional[str],
    telemetry: dict,
    chosen_line_id: Optional[str] = None,
    committed_line: Optional[dict] = None,
    rationale: Optional[str] = None,
    eval_metrics: Optional[dict] = None,
) -> None:
    """Persist one compact Reasoner investigation row (/reason)."""
    metrics = eval_metrics or {}
    committed = None
    complete = None
    if committed_line is not None:
        committed = True
        complete = bool(committed_line.get("complete"))
        chosen_line_id = chosen_line_id or committed_line.get("line_id")
    elif telemetry.get("terminal_kind") == "line":
        committed = True
    elif telemetry.get("terminal_kind") in ("goals", "base_search_fallback"):
        committed = False
    try:
        memory.record_reasoner_decision(
            game_id=game_id,
            turn=turn,
            decision_index=decision_index,
            root_state_hash=root_state_hash,
            telemetry=telemetry,
            chosen_line_id=chosen_line_id,
            committed=committed,
            chosen_line_complete=complete,
            rationale=rationale,
            model_calls=metrics.get("model_calls") or metrics.get("actor_model_calls"),
            prompt_tokens=metrics.get("prompt_tokens") or metrics.get("actor_prompt_tokens"),
            completion_tokens=(
                metrics.get("completion_tokens") or metrics.get("actor_completion_tokens")
            ),
        )
    except Exception as exc:
        logger.warning("Reasoner decision capture failed: %s", exc)


def capture_turn_snapshot(
    *,
    memory: Memory,
    game_id: str,
    turn: int,
    brief_state: dict,
    my_player_index: Optional[int] = None,
    turn_player_index: Optional[int] = None,
) -> None:
    """Persist one end-of-turn board pulse (/turn_snapshot)."""
    try:
        memory.record_turn_snapshot(
            game_id=game_id,
            turn=turn,
            my_player_index=(
                my_player_index
                if my_player_index is not None
                else brief_state.get("my_player_index")
            ),
            turn_player_index=(
                turn_player_index
                if turn_player_index is not None
                else brief_state.get("turn_player_index")
            ),
            scalars=snapshot_scalars(brief_state),
            brief_state=brief_state,
        )
    except Exception as exc:
        logger.warning("Turn snapshot record failed: %s", exc)


# ── Outcome / event / game-over capture ───────────────────────────────────────


def capture_outcome(*, memory: Memory, game_id: str, accepted: bool,
                    rejection_reason: Optional[str] = None) -> None:
    """Update the most recent unresolved decision row for a game (/outcome)."""
    if not game_id:
        return
    try:
        memory.update_acceptance_by_game(game_id, accepted, rejection_reason)
    except Exception as exc:
        logger.warning("Outcome update failed: %s", exc)


def capture_client_decision_metrics(*, memory: Memory, game_id: str, turn: int,
                                    decision_type: Optional[str], latency_ms: int,
                                    rejection_retries: int, heuristic_fallback: bool,
                                    accepted: Optional[bool]) -> None:
    """Persist engine-observed reliability metrics for one decision attempt."""
    try:
        memory.record_client_decision_metrics(
            game_id=game_id,
            turn=turn,
            decision_type=decision_type,
            latency_ms=latency_ms,
            rejection_retries=rejection_retries,
            heuristic_fallback=heuristic_fallback,
            accepted=accepted,
        )
    except Exception as exc:
        logger.warning("Client decision metrics record failed: %s", exc)


def capture_card_event(*, memory: Memory, game_id: str, turn: int, card_def_id: str,
                       event: str, instance_id: Optional[str] = None,
                       my_player_index: Optional[int] = None, energy_spent: int = 0,
                       breakdown_delta: Optional[dict] = None) -> None:
    """Persist one card lifecycle event (/card_event)."""
    try:
        memory.record_card_event(
            game_id=game_id,
            turn=turn,
            card_def_id=card_def_id,
            event=event,
            instance_id=instance_id,
            my_player_index=my_player_index,
            energy_spent=energy_spent,
            breakdown_delta=breakdown_delta,
        )
    except ValueError as exc:
        logger.warning("Card event rejected: %s", exc)
    except Exception as exc:
        logger.warning("Card event record failed: %s", exc)


def capture_opponent_action(*, memory: Memory, game_id: str, turn: int, action: str) -> None:
    """Persist a visible opponent action (/opponent_action)."""
    try:
        memory.record_opponent_action(game_id=game_id, turn=turn, action=action)
    except Exception as exc:
        logger.warning("Opponent action record failed: %s", exc)


def capture_game_over(*, memory: Memory, game_id: str, winner_index: int,
                      my_player_index: int, my_score: int, opp_score: int,
                      total_turns: int, first_player_index: int = -1,
                      seed: Optional[str] = None) -> dict:
    """Record a finished game + backfill its tuning rows (/game_over).

    Returns the eval scorecard summary (or an empty dict) so the caller can log
    it. ``outcome`` is included in the return for convenience.
    """
    outcome = "win" if winner_index == my_player_index else "loss"
    first_player = first_player_index if first_player_index >= 0 else None
    if my_player_index == 0:
        p0_score, p1_score = my_score, opp_score
    else:
        p0_score, p1_score = opp_score, my_score
    try:
        memory.record_game_outcome(
            game_id=game_id,
            outcome=outcome,
            my_score=my_score,
            opp_score=opp_score,
            turns_played=total_turns,
            first_player_index=first_player,
            seed=seed,
            winner_index=winner_index if winner_index >= 0 else None,
            p0_score=p0_score,
            p1_score=p1_score,
        )
    except Exception as exc:
        logger.warning("Game outcome record failed: %s", exc)

    # Backfill the tuning dataset: label every search_decisions row for this game
    # with the final result + initiative. Without this the tuner has no label.
    try:
        memory.backfill_game_outcome(
            game_id=game_id,
            game_outcome=outcome,
            final_score_diff=my_score - opp_score,
            my_player_index=my_player_index,
            first_player_index=first_player,
        )
    except Exception as exc:
        logger.warning("Search decision backfill failed: %s", exc)

    summary: dict = {}
    try:
        summary = memory.summarize_game_eval(game_id)
    except Exception as exc:
        logger.warning("Eval summary failed: %s", exc)
    summary["outcome"] = outcome
    return summary
