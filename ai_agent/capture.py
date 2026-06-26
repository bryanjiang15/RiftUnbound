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

import logging
from typing import Any, Callable, Optional

from .memory import Memory
from .schemas import Decision, DecisionRequest

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
    return {
        "my_score": brief_state.get("my_score"),
        "opp_score": brief_state.get("opponent_score"),
        "my_energy": brief_state.get("my_energy"),
        "board_might_diff": board_might_diff,
        "cards_in_hand": len(brief_state.get("my_hand", []) or []),
        "cards_in_hand_opp": brief_state.get("opponent_hand_size"),
        "bf_control_net": bf_control_net,
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
            }
        )

    turn = brief_state.get("turn_number", 0)
    decision_type = brief_state.get("decision_type", "unknown")
    mode = request.search_stats.mode if request.search_stats else "main"
    # Attribute this row to the seat's actual profile (per-seat), not the single
    # profile the server read at startup.
    weight_version_id = weight_resolver(request.scoring_profile_json)

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
    )
    memory.record_decision_snapshot(
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        scalars=snapshot_scalars(brief_state),
        brief_state=brief_state,
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
            )
        except Exception as exc:
            logger.warning("Search decision capture failed: %s", exc)


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
    try:
        memory.record_game_outcome(
            game_id=game_id,
            outcome=outcome,
            my_score=my_score,
            opp_score=opp_score,
            turns_played=total_turns,
            first_player_index=first_player,
            seed=seed,
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
