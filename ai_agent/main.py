"""
Riftbound AI Agent — FastAPI Service

Endpoints:
  POST /decision         Main entry: receive DecisionRequest, run agent loop,
                         return Decision JSON.
  GET  /health           Liveness check.
  GET  /legal_moves      Return the current legal moves list (for debugging).
  GET  /state            Return the full state text (for debugging).
  GET  /card/{card_id}   Return a card definition (read skill proxy).
  GET  /rule             Lookup rules passage (read skill proxy).

Godot communicates only through POST /decision.  All other endpoints are
for debugging and the Python skill layer's internal use.

Usage:
  uvicorn ai_agent.main:app --port 8765 --reload

Set OPENAI_API_KEY in your environment before starting.
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from . import skills as skill_module
from .agent import (
    _GAME_STATE_LOG_PATH,
    PIPELINE_LEGACY,
    PIPELINE_STAGED,
    decide,
    _INPUT_LOG_PATH,
    _PLAN_LOG_PATH,
    _LOG_INPUTS,
    _log_game_state_event,
    choose_line,
)
from .memory import DecisionLogger, Memory
from .schemas import Decision, DecisionRequest, Move

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Global singletons created at startup
_memory: Memory | None = None
_decision_logger: DecisionLogger | None = None
_pipeline_mode: str = PIPELINE_LEGACY
_search_enabled: bool = False
_argmax_enabled: bool = False
_weight_version_id: int | None = None
_data_origin: str = "vs_human"
_SEARCH_LOG_PATH = os.path.join(os.path.dirname(__file__), "agent_search.log")


def _load_scoring_profile() -> str | None:
    """Read the active scoring profile JSON (the weights being tuned)."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "Data", "AI", "scoring_profile.json"
    )
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        logger.warning("Could not read scoring profile at %s: %s", path, exc)
        return None


def _current_git_sha() -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = out.stdout.strip()
        return sha or None
    except (OSError, subprocess.SubprocessError):
        return None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _memory, _decision_logger, _pipeline_mode, _search_enabled
    global _argmax_enabled, _weight_version_id, _data_origin
    db_path_override = os.environ.get("RIFTBOUND_DB_PATH", "").strip()
    if db_path_override:
        from pathlib import Path

        _memory = Memory(db_path=Path(db_path_override))
        logger.info("Memory DB path override: %s", db_path_override)
    else:
        _memory = Memory()
    _decision_logger = DecisionLogger()
    _decision_logger.clear()          # fresh log on every server start
    requested_pipeline = os.environ.get("RIFTBOUND_PIPELINE", PIPELINE_LEGACY).strip().lower()
    _pipeline_mode = (
        requested_pipeline
        if requested_pipeline in (PIPELINE_LEGACY, PIPELINE_STAGED)
        else PIPELINE_LEGACY
    )
    _search_enabled = os.environ.get("RIFTBOUND_SEARCH", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    _argmax_enabled = os.environ.get("RIFTBOUND_SEARCH_ARGMAX", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    # Provenance tag for captured rows: 'vs_human' (default live play),
    # 'self_play', or 'vs_heuristic'. The self-play harness sets this so the two
    # state distributions are never silently mixed in tuning.
    _data_origin = os.environ.get("RIFTBOUND_DATA_ORIGIN", "vs_human").strip() or "vs_human"
    # Record the active scoring profile so every captured decision is attributable
    # to the exact weights that produced it (A/B + tuning provenance).
    profile_json = _load_scoring_profile()
    if profile_json is not None:
        try:
            _weight_version_id = _memory.record_weight_version(
                profile_json=profile_json, git_sha=_current_git_sha()
            )
        except Exception as exc:
            logger.warning("Weight version record failed: %s", exc)
    if _LOG_INPUTS:
        _INPUT_LOG_PATH.write_text(
            f"Riftbound AI Agent — Input Log\nStarted: "
            f"{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            + "═" * 72 + "\n",
            encoding="utf-8",
        )
        _PLAN_LOG_PATH.write_text(
            f"Riftbound AI Agent — Plan Log\nStarted: "
            f"{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            + "═" * 72 + "\n",
            encoding="utf-8",
        )
        _GAME_STATE_LOG_PATH.write_text(
            f"Riftbound AI Agent — Game State Log\nStarted: "
            f"{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            + "=" * 72 + "\n",
            encoding="utf-8",
        )
    logger.info("Riftbound AI agent service started.")
    logger.info("OpenAI API key: %s", "set" if os.environ.get("OPENAI_API_KEY") else "NOT SET")
    logger.info("Input logging: %s", "ENABLED → agent_inputs.log" if _LOG_INPUTS else "disabled")
    logger.info("Plan logging: %s", "ENABLED → agent_plans.log" if _LOG_INPUTS else "disabled")
    logger.info("Game state logging: %s", "ENABLED → agent_game_state.log" if _LOG_INPUTS else "disabled")
    logger.info("Pipeline mode: %s", _pipeline_mode)
    logger.info("Search mode: %s", "ENABLED" if _search_enabled else "disabled")
    logger.info("Argmax-only selection: %s", "ENABLED" if _argmax_enabled else "disabled")
    logger.info("Weight version id: %s", _weight_version_id)
    yield
    logger.info("Riftbound AI agent service shutting down.")


app = FastAPI(
    title="Riftbound AI Agent",
    description="Python reasoning agent for the Riftbound TCG simulator.",
    version="1.0.0",
    lifespan=_lifespan,
)


def _log_search_payload(game_id: str, request: DecisionRequest) -> None:
    if not (_LOG_INPUTS and _search_enabled):
        return
    if not request.candidate_lines:
        return
    try:
        mode = request.search_stats.mode if request.search_stats else "main"
        lines = [
            "",
            "═" * 72,
            f"Search payload [{mode}]: game={game_id} "
            f"turn={request.brief_state.turn_number} "
            f"type={request.brief_state.decision_type}",
            "═" * 72,
        ]
        if request.search_stats:
            lines.append("Stats:")
            lines.append(json.dumps(request.search_stats.model_dump(), indent=2))
        lines.append("Candidate lines:")
        for line in request.candidate_lines:
            lines.append("")
            lines.append(f"{line.line_id} | score={line.score:.3f}")
            lines.append("Steps:")
            commands = [
                m.to_command() if hasattr(m, "to_command") else str(m)
                for m in line.moves
            ]
            for i, cmd in enumerate(commands):
                ctx = line.move_contexts[i] if i < len(line.move_contexts) else {}
                kind = ctx.get("kind", "scripted")
                context_text = ctx.get("context", "")
                if kind == "intermediate":
                    note = context_text or "auto-resolved decision"
                    lines.append(f"  - {cmd}    ← [intermediate] {note}")
                elif context_text:
                    lines.append(f"  - {cmd}    ({context_text})")
                else:
                    lines.append(f"  - {cmd}")
            lines.append("Breakdown:")
            lines.append(json.dumps(line.score_breakdown, indent=2, default=str))
            lines.append("Resolved delta:")
            lines.append(json.dumps(line.resolved_state, indent=2, default=str))
            if line.opponent_windows:
                lines.append("Opponent windows:")
                lines.append(json.dumps([w.model_dump() for w in line.opponent_windows], indent=2))
        with open(_SEARCH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as exc:
        logger.warning("Search log write failed: %s", exc)


def _log_search_deferral(game_id: str, request: DecisionRequest) -> None:
    """Record turns where search mode is on but no candidate lines were supplied,
    so the decision fell back to the staged/legacy agent pipeline.

    Godot only runs the turn search when, at this decision, it is the AI's turn
    AND the engine is in the MAIN phase / NEUTRAL_OPEN state (a fresh main-phase
    choice). `decision_type == "main_phase"` is a catch-all label and does NOT
    guarantee that state, so we surface the actual phase/state/seat here to make
    the real deferral cause visible rather than guessed."""
    if not (_LOG_INPUTS and _search_enabled):
        return
    try:
        bs = request.brief_state
        my_turn = bs.turn_player_index == bs.my_player_index
        dtype = str(bs.decision_type).strip().lower()
        phase = bs.current_phase.strip().lower()
        state = bs.current_state.strip().lower()
        reasons = []
        # chain_reaction / showdown_focus are reactive-search windows; if we
        # reached the deferral path for one, the reactive search produced no
        # lines (e.g. nothing but an unavailable response) rather than this being
        # an ineligible decision type.
        is_reactive_window = dtype in ("chain_reaction", "showdown_focus")
        if is_reactive_window:
            reasons.append(
                f"reactive window ({dtype}) produced no candidate lines"
            )
        else:
            if not my_turn:
                reasons.append("not AI's turn")
            if phase != "main phase":
                reasons.append(f"phase={bs.current_phase} (need Main Phase)")
            if state != "neutral open":
                reasons.append(f"state={bs.current_state} (need Neutral Open)")
        if request.rejection_context is not None:
            reasons.append("retry after rejected move")
        if not reasons:
            reasons.append(
                "search ran but returned no candidate lines "
                "(mid-line execution, or only 'end turn' was legal)"
            )
        lines = [
            "",
            "═" * 72,
            f"Search DEFERRED to {_pipeline_mode} agent: "
            f"game={game_id} turn={bs.turn_number} type={bs.decision_type}",
            f"  phase={bs.current_phase} state={bs.current_state} "
            f"turn_player={bs.turn_player_index} me={bs.my_player_index}",
            "  Reason: " + "; ".join(reasons),
            "═" * 72,
        ]
        with open(_SEARCH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as exc:
        logger.warning("Search deferral log write failed: %s", exc)


# ── Tuning dataset capture ────────────────────────────────────────────────────


def _snapshot_scalars(brief_state: dict) -> dict:
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


def _capture_search_decision(
    *,
    game_id: str,
    decision_index: int,
    brief_state: dict,
    request: DecisionRequest,
    decision: Decision,
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

    _memory.record_search_decision(
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
        origin=_data_origin,
        weight_version_id=_weight_version_id,
        candidates=cand_rows,
    )
    _memory.record_decision_snapshot(
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        scalars=_snapshot_scalars(brief_state),
        brief_state=brief_state,
    )


# ── Main decision endpoint ────────────────────────────────────────────────────


@app.post("/decision", response_model=Decision)
async def decision_endpoint(request: DecisionRequest) -> Decision:
    """
    Receive a BriefState from Godot, run the reasoning loop, and return a Decision.

    The Decision's move.to_command() gives the Godot console command string.
    Godot validates legality; on rejection it may call this endpoint again with
    a rejection_context.
    """
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    brief_state = request.brief_state.model_dump()
    game_id = request.game_id

    # Install state so skills can serve it
    skill_module.set_state(brief_state)

    rejection_ctx = (
        request.rejection_context.model_dump() if request.rejection_context else None
    )

    logger.info(
        "Decision request: game=%s turn=%s type=%s",
        game_id,
        brief_state.get("turn_number", "?"),
        brief_state.get("decision_type", "?"),
    )

    _log_search_payload(game_id, request)

    # Run reasoning loop
    eval_metrics: dict = {}
    if _search_enabled and request.candidate_lines:
        decision = await choose_line(
            brief_state=brief_state,
            game_id=game_id,
            memory=_memory,
            candidate_lines=request.candidate_lines,
            search_stats=request.search_stats,
            eval_metrics=eval_metrics,
            argmax_only=_argmax_enabled,
        )
    else:
        if _search_enabled:
            _log_search_deferral(game_id, request)
        decision = await decide(
            brief_state=brief_state,
            game_id=game_id,
            memory=_memory,
            rejection_context=rejection_ctx,
            eval_metrics=eval_metrics,
            pipeline_mode=_pipeline_mode,
        )

    # Record in episodic memory (accepted status unknown until Godot responds)
    try:
        _memory.record(
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
        decision_index = (
            _memory._decision_counters.get(game_id, 0) - 1 if _memory else 0
        )
        _memory.record_decision_metrics(
            game_id=game_id,
            turn=brief_state.get("turn_number", 0),
            decision_index=decision_index,
            decision_type=brief_state.get("decision_type", "unknown"),
            metrics=eval_metrics,
        )
    except Exception as exc:
        logger.warning("Decision metrics record failed: %s", exc)

    # Capture the tuning dataset row (search_decisions + candidate_lines +
    # decision_snapshots) when this decision came from the engine search.
    if _search_enabled and request.candidate_lines:
        try:
            decision_index = (
                _memory._decision_counters.get(game_id, 0) - 1 if _memory else 0
            )
            _capture_search_decision(
                game_id=game_id,
                decision_index=decision_index,
                brief_state=brief_state,
                request=request,
                decision=decision,
            )
        except Exception as exc:
            logger.warning("Search decision capture failed: %s", exc)

    # Write human-readable decision log
    if _decision_logger:
        try:
            _decision_logger.log(
                game_id=game_id,
                turn=brief_state.get("turn_number", 0),
                decision_index=_memory._decision_counters.get(game_id, 0) - 1 if _memory else 0,
                decision_type=brief_state.get("decision_type", "unknown"),
                reasoning=decision.reasoning,
                move=decision.move.model_dump(),
                command=decision.move.to_command(),
                confidence=decision.confidence,
                alternatives_considered=decision.alternatives_considered,
            )
        except Exception as exc:
            logger.warning("Decision log write failed: %s", exc)

    logger.info(
        "Returning decision: action=%s | reasoning=%.120s",
        decision.move.action,
        decision.reasoning,
    )
    return decision


# ── Outcome / game-over reporting (called by Godot) ──────────────────────────


class GameOverRequest(BaseModel):
    game_id: str
    winner_index: int
    my_player_index: int
    my_score: int
    opp_score: int
    total_turns: int
    first_player_index: int = -1  # which seat took turn 1 (-1 = unknown)
    seed: str | None = None       # deck/shuffle seed (self-play reproducibility)


class OpponentActionRequest(BaseModel):
    game_id: str
    turn: int
    action: str


class GameStateEventRequest(BaseModel):
    game_id: str
    turn: int = 0
    event_type: str
    description: str
    actor: str | None = None
    command: str | None = None
    decision_type: str | None = None
    state: dict[str, Any] | None = None


@app.post("/outcome")
async def outcome_endpoint(body: dict) -> dict:
    """
    Godot calls this after applying or rejecting a move.
    Body: { game_id, accepted: bool, rejection_reason: str|null }
    Updates the most recent unresolved decision row for this game.
    """
    if _memory is None:
        return {"status": "no-op"}
    game_id = body.get("game_id", "")
    accepted = bool(body.get("accepted", True))
    rejection_reason = body.get("rejection_reason") or None
    if game_id:
        try:
            _memory.update_acceptance_by_game(game_id, accepted, rejection_reason)
        except Exception as exc:
            logger.warning("Outcome update failed: %s", exc)
    logger.info("Outcome: game=%s accepted=%s", game_id, accepted)
    return {"status": "ok"}


@app.post("/game_over")
async def game_over_endpoint(body: GameOverRequest) -> dict:
    """
    Godot calls this when a game ends. Records win/loss for future phases.
    Does not trigger reflection yet (Phase 3).
    """
    if _memory is None:
        return {"status": "no-op"}
    outcome = "win" if body.winner_index == body.my_player_index else "loss"
    first_player = body.first_player_index if body.first_player_index >= 0 else None
    try:
        _memory.record_game_outcome(
            game_id=body.game_id,
            outcome=outcome,
            my_score=body.my_score,
            opp_score=body.opp_score,
            turns_played=body.total_turns,
            first_player_index=first_player,
            seed=body.seed,
        )
    except Exception as exc:
        logger.warning("Game outcome record failed: %s", exc)

    # Backfill the tuning dataset: label every search_decisions row for this game
    # with the final result + initiative. Without this the tuner has no label.
    try:
        _memory.backfill_game_outcome(
            game_id=body.game_id,
            game_outcome=outcome,
            final_score_diff=body.my_score - body.opp_score,
            my_player_index=body.my_player_index,
            first_player_index=first_player,
        )
    except Exception as exc:
        logger.warning("Search decision backfill failed: %s", exc)

    # Aggregate the reliability scorecard for this finished game (eval track).
    try:
        summary = _memory.summarize_game_eval(body.game_id)
        logger.info(
            "Eval scorecard: game=%s decisions=%d model_calls=%d avg_latency=%.0fms "
            "p95=%dms parse_retries=%d legality_retries=%d fallbacks=%d",
            body.game_id,
            summary["decisions"],
            summary["model_calls_total"],
            summary["avg_latency_ms"],
            summary["p95_latency_ms"],
            summary["parse_retry_total"],
            summary["legality_retry_total"],
            summary["fallback_count"],
        )
    except Exception as exc:
        logger.warning("Eval summary failed: %s", exc)

    logger.info(
        "Game over: game=%s outcome=%s score=%d-%d turns=%d",
        body.game_id, outcome, body.my_score, body.opp_score, body.total_turns,
    )
    return {"status": "ok", "outcome": outcome}


# ── Evaluation endpoints (reliability + human feedback) ──────────────────────


class DecisionMetricsRequest(BaseModel):
    game_id: str
    turn: int = 0
    decision_type: str | None = None
    latency_ms: int = 0
    rejection_retries: int = 0
    heuristic_fallback: bool = False
    accepted: bool | None = None


class HumanFeedbackRequest(BaseModel):
    game_id: str
    reviewer: str | None = None
    scope: str = "game"          # 'game' | 'decision'
    turn: int | None = None
    decision_index: int | None = None
    strategic: int | None = None
    tactical: int | None = None
    resource: int | None = None
    rules: int | None = None
    overall: int | None = None
    tags: list[str] | None = None
    note: str | None = None


class MoveFeedbackRequest(BaseModel):
    game_id: str
    sentiment: str               # 'like' | 'neutral' | 'dislike'
    turn: int | None = None
    move_seq: int | None = None
    move_desc: str | None = None
    reviewer: str | None = None


@app.post("/decision_metrics")
async def decision_metrics_endpoint(body: DecisionMetricsRequest) -> dict:
    """Godot reports engine-observed metrics for one AI decision (eval track)."""
    if _memory is None:
        return {"status": "no-op"}
    try:
        _memory.record_client_decision_metrics(
            game_id=body.game_id,
            turn=body.turn,
            decision_type=body.decision_type,
            latency_ms=body.latency_ms,
            rejection_retries=body.rejection_retries,
            heuristic_fallback=body.heuristic_fallback,
            accepted=body.accepted,
        )
    except Exception as exc:
        logger.warning("Client decision metrics record failed: %s", exc)
    return {"status": "ok"}


@app.post("/human_feedback")
async def human_feedback_endpoint(body: HumanFeedbackRequest) -> dict:
    """Receive a human evaluation submission from the Godot feedback panel."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    try:
        row_id = _memory.record_human_feedback(game_id=body.game_id, feedback=body.model_dump())
    except Exception as exc:
        logger.warning("Human feedback record failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not record feedback") from exc
    logger.info("Human feedback recorded: game=%s scope=%s id=%d", body.game_id, body.scope, row_id)
    return {"status": "ok", "id": row_id}


@app.post("/move_feedback")
async def move_feedback_endpoint(body: MoveFeedbackRequest) -> dict:
    """Receive a per-move sentiment (like/neutral/dislike) from the live feedback box."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    if body.sentiment not in ("like", "neutral", "dislike"):
        raise HTTPException(status_code=422, detail="Invalid sentiment")
    try:
        row_id = _memory.record_move_feedback(
            game_id=body.game_id,
            sentiment=body.sentiment,
            turn=body.turn,
            move_seq=body.move_seq,
            move_desc=body.move_desc,
            reviewer=body.reviewer,
        )
    except Exception as exc:
        logger.warning("Move feedback record failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not record move feedback") from exc
    return {"status": "ok", "id": row_id}


@app.get("/eval_report")
async def eval_report_endpoint() -> dict:
    """Aggregate reliability + human-feedback scorecard across all recorded games."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return _memory.eval_report()


@app.post("/opponent_action")
async def opponent_action_endpoint(body: OpponentActionRequest) -> dict:
    """
    Godot calls this whenever an opponent action becomes publicly visible.
    Stored and injected into agent context as opponent history.
    """
    if _memory is None:
        return {"status": "no-op"}
    try:
        _memory.record_opponent_action(
            game_id=body.game_id,
            turn=body.turn,
            action=body.action,
        )
    except Exception as exc:
        logger.warning("Opponent action record failed: %s", exc)
    logger.debug("Opponent action: game=%s turn=%d action=%s", body.game_id, body.turn, body.action)
    return {"status": "ok"}


@app.post("/game_state_event")
async def game_state_event_endpoint(body: GameStateEventRequest) -> dict:
    """
    Godot posts debug timeline events here. Meaningful AI decisions and engine
    resolution milestones include a post-event BriefState; opponent actions are
    logged as one-line events without state snapshots.
    """
    if not _LOG_INPUTS:
        return {"status": "disabled"}
    try:
        _log_game_state_event(
            game_id=body.game_id,
            turn=body.turn,
            event_type=body.event_type,
            description=body.description,
            actor=body.actor,
            command=body.command,
            decision_type=body.decision_type,
            state=body.state,
        )
    except Exception as exc:
        logger.warning("Game state event log failed: %s", exc)
    return {"status": "ok"}


# ── Debug / read-skill proxy endpoints ────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "version": "1.0.0",
        "search_enabled": _search_enabled,
        "pipeline": _pipeline_mode,
    }


@app.get("/legal_moves")
async def get_legal_moves() -> dict:
    return {"legal_moves": skill_module.list_legal_moves()}


@app.get("/state")
async def get_state() -> dict:
    text = skill_module.get_full_state()
    return {"state": text}


@app.get("/card/{card_id}")
async def get_card(card_id: str) -> dict:
    detail = skill_module.get_card_detail(card_id)
    try:
        return json.loads(detail)
    except json.JSONDecodeError:
        return {"detail": detail}


@app.get("/rule")
async def get_rule(q: str = "") -> dict:
    result = skill_module.lookup_rule(q)
    return {"result": result}


@app.get("/position")
async def get_position() -> dict:
    return skill_module.evaluate_position()
