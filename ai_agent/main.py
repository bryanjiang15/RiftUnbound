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
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from pydantic import BaseModel

# Load .env BEFORE importing .agent: agent.py computes _LOG_INPUTS from the
# environment at import time (module-level constant), so the .env values must be
# present in os.environ first. If this ran after `from .agent import _LOG_INPUTS`,
# the flag would freeze to its pre-.env default (False) and no file logs would be
# written even with RIFTBOUND_LOG_INPUTS=1 set in .env.
from dotenv import load_dotenv

load_dotenv()

from . import skills as skill_module
from . import capture as capture_mod
from .agent import (
    _GAME_STATE_LOG_PATH,
    PIPELINE_LEGACY,
    PIPELINE_STAGED,
    decide,
    _INPUT_LOG_PATH,
    _PLAN_LOG_PATH,
    _LOG_INPUTS,
    _log_game_state_event,
    build_goal_overlay,
    choose_line,
    run_reasoner,
)
from .goal_compiler import compile_goals
from .memory import DecisionLogger, Memory
from .reasoner import empty_reasoner_emit
from .schemas import Decision, DecisionRequest, GoalsRequest, Move, ReasonRequest
from .search_log_fmt import (
    BOLD,
    CYAN,
    DIM,
    MAGENTA,
    YELLOW,
    format_banner,
    format_breakdown_line,
    format_delta_line,
    format_line_header,
    format_stats_line,
    paint,
)

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
_goals_enabled: bool = False
_reasoner_enabled: bool = False
_weight_version_id: int | None = None
_data_origin: str = "vs_human"
# When set (0 or 1), only persist the tuning dataset (search_decisions /
# candidate_lines / decision_snapshots) for that seat's decisions. Lets a
# self-play run pit two profiles against each other while storing data from only
# one of them (put the profile-under-test on this seat). None = capture both.
_capture_seat: int | None = None
_SEARCH_LOG_PATH = os.path.join(os.path.dirname(__file__), "agent_search.log")

# Cache of profile-JSON text -> weight_versions.id, so a per-request profile is
# registered/looked up once instead of hitting the DB on every decision.
_weight_version_cache: dict[str, int] = {}
# Goal overlays (+ GoalSet) emitted by the Reasoner must also be reused by
# /decision for situational/card re-ranking and SQL goal telemetry.
# Value: (ProfileOverlay, GoalSet | None)
_reasoner_overlays: dict[tuple[str, int, str], tuple[Any, Any]] = {}


def _reasoner_overlay_key(
    game_id: str, brief_state: dict[str, Any]
) -> tuple[str, int, str]:
    """Scope a Reasoner overlay to the exact decision window it was built for."""
    return (
        game_id,
        int(brief_state.get("turn_number", 0)),
        str(brief_state.get("decision_type", "unknown")).strip().lower(),
    )


def _resolve_weight_version(profile_json: str | None) -> int | None:
    """Map a request's scoring-profile JSON to its weight_versions id.

    Per-seat attribution: the engine sends the seat's actual profile, so two
    profiles in one self-play run get their own ids instead of both collapsing
    onto the single file the server read at startup. Falls back to that startup
    id when the request carries no profile (e.g. live play / older engines).
    """
    if not profile_json:
        return _weight_version_id
    cached = _weight_version_cache.get(profile_json)
    if cached is not None:
        return cached
    try:
        wv = _memory.record_weight_version(
            profile_json=profile_json, git_sha=_current_git_sha()
        )
    except Exception as exc:
        logger.warning("Per-request weight version resolve failed: %s", exc)
        return _weight_version_id
    _weight_version_cache[profile_json] = wv
    return wv


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
    global _argmax_enabled, _weight_version_id, _data_origin, _capture_seat
    global _goals_enabled, _reasoner_enabled
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
    # Goal-oriented strategist: when on (and search is on, argmax off), an LLM sets
    # 1–4 per-turn goals that are compiled into a transient scoring overlay biasing
    # line selection. Off by default so the proven base-profile search stays the
    # floor and argmax self-play remains LLM-free.
    _goals_enabled = os.environ.get("RIFTBOUND_GOALS", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    reasoner_requested = os.environ.get("RIFTBOUND_REASONER", "off").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    _reasoner_enabled = reasoner_requested and _search_enabled and not _argmax_enabled
    if reasoner_requested and not _reasoner_enabled:
        logger.warning(
            "RIFTBOUND_REASONER ignored: it requires RIFTBOUND_SEARCH=on and "
            "RIFTBOUND_SEARCH_ARGMAX=off."
        )
    # Provenance tag for captured rows: 'vs_human' (default live play),
    # 'self_play', or 'vs_heuristic'. The self-play harness sets this so the two
    # state distributions are never silently mixed in tuning.
    _data_origin = os.environ.get("RIFTBOUND_DATA_ORIGIN", "vs_human").strip() or "vs_human"
    # Optional capture filter: persist tuning rows for only one seat's decisions.
    capture_seat_raw = os.environ.get("RIFTBOUND_CAPTURE_SEAT", "").strip()
    if capture_seat_raw in ("0", "1"):
        _capture_seat = int(capture_seat_raw)
    else:
        _capture_seat = None
        if capture_seat_raw:
            logger.warning(
                "Ignoring invalid RIFTBOUND_CAPTURE_SEAT=%r (expected 0 or 1)",
                capture_seat_raw,
            )
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
        with open(_SEARCH_LOG_PATH, "w", encoding="utf-8") as f:
            started = __import__("datetime").datetime.utcnow().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            f.write(
                paint("Riftbound AI Agent — Search & Goal Log", BOLD + CYAN)
                + "\n"
                + f"Started: {started} UTC\n"
                + paint("═" * 72, DIM)
                + "\n"
            )
    logger.info("Riftbound AI agent service started.")
    _provider = os.environ.get("RIFTBOUND_LLM_PROVIDER", "openai").strip().lower()
    if _provider == "azure":
        logger.info("LLM provider: Azure OpenAI")
        logger.info("Azure endpoint: %s", "set" if os.environ.get("AZURE_OPENAI_ENDPOINT") else "NOT SET")
        logger.info("Azure API key: %s", "set" if os.environ.get("AZURE_OPENAI_API_KEY") else "NOT SET")
    else:
        logger.info("LLM provider: OpenAI")
        logger.info("OpenAI API key: %s", "set" if os.environ.get("OPENAI_API_KEY") else "NOT SET")
    logger.info("Input logging: %s", "ENABLED → agent_inputs.log" if _LOG_INPUTS else "disabled")
    logger.info("Plan logging: %s", "ENABLED → agent_plans.log" if _LOG_INPUTS else "disabled")
    logger.info(
        "Tool logging: %s",
        "ENABLED → agent_search.log" if _LOG_INPUTS else "disabled",
    )
    logger.info("Game state logging: %s", "ENABLED → agent_game_state.log" if _LOG_INPUTS else "disabled")
    logger.info("Pipeline mode: %s", _pipeline_mode)
    logger.info("Search mode: %s", "ENABLED" if _search_enabled else "disabled")
    logger.info("Argmax-only selection: %s", "ENABLED" if _argmax_enabled else "disabled")
    logger.info("Goal strategist: %s", "ENABLED" if _goals_enabled else "disabled")
    logger.info("Phase-3 Reasoner: %s", "ENABLED" if _reasoner_enabled else "disabled")
    logger.info(
        "Search & goal log: %s",
        ("ENABLED → %s" % _SEARCH_LOG_PATH) if (_LOG_INPUTS and _search_enabled)
        else "disabled (needs RIFTBOUND_LOG_INPUTS=1 AND RIFTBOUND_SEARCH=on)",
    )
    if (_search_enabled or _goals_enabled) and not _LOG_INPUTS:
        logger.warning(
            "Search/goals are ON but RIFTBOUND_LOG_INPUTS is not set — "
            "no search or goal logs will be written. Start with "
            "RIFTBOUND_LOG_INPUTS=1 to populate %s.",
            _SEARCH_LOG_PATH,
        )
    logger.info("Weight version id: %s", _weight_version_id)
    logger.info(
        "Capture seat filter: %s",
        "both seats" if _capture_seat is None else "seat %d only" % _capture_seat,
    )
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
        title = (
            f"Search payload [{mode}]: game={game_id} "
            f"turn={request.brief_state.turn_number} "
            f"type={request.brief_state.decision_type}"
        )
        lines = format_banner(title)
        if request.search_stats:
            lines.append(format_stats_line(request.search_stats.model_dump()))
        lines.append(paint("Candidate lines:", BOLD))
        for line in request.candidate_lines:
            lines.append("")
            lines.append(format_line_header(line.line_id, float(line.score)))
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
                    lines.append(
                        f"  - {cmd}    "
                        f"{paint('← [intermediate]', DIM + YELLOW)} "
                        f"{paint(note, DIM)}"
                    )
                elif context_text:
                    lines.append(f"  - {cmd}    {paint(f'({context_text})', DIM)}")
                else:
                    lines.append(f"  - {cmd}")
            lines.append("  " + format_breakdown_line(line.score_breakdown or {}))
            lines.append("  " + format_delta_line(line.resolved_state or {}))
            if line.opponent_windows:
                windows = [w.model_dump() for w in line.opponent_windows]
                lines.append(
                    "  "
                    + paint("Opp windows:", DIM)
                    + " "
                    + paint(json.dumps(windows, default=str, separators=(",", ":")), DIM)
                )
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
        title = (
            f"Search DEFERRED to {_pipeline_mode} agent: "
            f"game={game_id} turn={bs.turn_number} type={bs.decision_type}"
        )
        lines = format_banner(title)
        lines.extend(
            [
                f"  phase={bs.current_phase} state={bs.current_state} "
                f"turn_player={bs.turn_player_index} me={bs.my_player_index}",
                "  " + paint("Reason:", MAGENTA) + " " + "; ".join(reasons),
            ]
        )
        with open(_SEARCH_LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as exc:
        logger.warning("Search deferral log write failed: %s", exc)


# ── Tuning dataset capture ────────────────────────────────────────────────────
# The capture helpers (snapshot scalars, search-decision rows, game-over
# backfill) live in ai_agent/capture.py so the live HTTP path and the offline
# self-play importer write identical data. The endpoints below call into it.


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
    overlay = None
    goal_set = None
    goals_source = "none"
    if _search_enabled and request.candidate_lines:
        # With fewer than two candidate lines there is nothing to bias/select, so
        # skip the strategist overlay (choose_line will short-circuit to the single
        # line). Goals only matter when the search actually offers a choice.
        if _reasoner_enabled:
            cached = _reasoner_overlays.get(
                _reasoner_overlay_key(game_id, brief_state)
            )
            if cached is not None:
                overlay, goal_set = cached
                goals_source = "reasoner"
        elif _goals_enabled and not _argmax_enabled and len(request.candidate_lines) > 1:
            try:
                overlay, goal_set = await build_goal_overlay(
                    brief_state=brief_state,
                    game_id=game_id,
                    memory=_memory,
                    eval_metrics=eval_metrics,
                )
                goals_source = "strategist"
            except Exception as exc:
                logger.warning("Goal overlay failed (%s); selecting under base profile", exc)
                overlay = None
                goal_set = None
                goals_source = "none"
        decision = await choose_line(
            brief_state=brief_state,
            game_id=game_id,
            memory=_memory,
            candidate_lines=request.candidate_lines,
            search_stats=request.search_stats,
            eval_metrics=eval_metrics,
            argmax_only=_argmax_enabled,
            overlay=overlay,
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

    # Record episodic memory, server-side eval metrics, and the tuning dataset
    # row in one place shared with the offline importer (see ai_agent/capture.py).
    capture_mod.capture_decision(
        memory=_memory,
        brief_state=brief_state,
        request=request,
        decision=decision,
        eval_metrics=eval_metrics,
        search_enabled=_search_enabled,
        data_origin=_data_origin,
        capture_seat=_capture_seat,
        weight_resolver=_resolve_weight_version,
        goals_source=goals_source,
        goal_set=goal_set,
        overlay=overlay,
    )

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


class CardEventRequest(BaseModel):
    game_id: str
    turn: int = 0
    card_def_id: str              # base definition_id (aggregation key)
    event: str                    # drawn|played|discarded|died|mulliganed|
                                  # scored|left_in_hand_at_end|in_opening_hand
    instance_id: str | None = None
    my_player_index: int | None = None
    energy_spent: int = 0
    breakdown_delta: dict[str, Any] | None = None


class TurnSnapshotRequest(BaseModel):
    game_id: str
    turn: int = 0
    brief_state: dict[str, Any]
    my_player_index: int | None = None
    turn_player_index: int | None = None


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
    summary = capture_mod.capture_game_over(
        memory=_memory,
        game_id=body.game_id,
        winner_index=body.winner_index,
        my_player_index=body.my_player_index,
        my_score=body.my_score,
        opp_score=body.opp_score,
        total_turns=body.total_turns,
        first_player_index=body.first_player_index,
        seed=body.seed,
    )
    outcome = summary.get("outcome", "loss")

    # Aggregate the reliability scorecard for this finished game (eval track).
    try:
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
        logger.warning("Eval summary log failed: %s", exc)

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


class AnalysisDecisionKey(BaseModel):
    game_id: str
    turn: int
    decision_index: int
    persist: bool = True
    mode: str = "outcome_rollout"  # outcome_rollout | same_turn
    preset: str = "deep"  # fast | deep
    future_player_turns: int = 4
    force_same_turn: bool = False
    target: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None


class FailureReportRequest(AnalysisDecisionKey):
    with_counterfactual: bool = True
    # When set, skip re-running CF and classify against this prior CF result.
    counterfactual_result: dict[str, Any] | None = None


def _json_maybe(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


_SEARCH_DECISION_UI_KEYS = (
    "id",
    "game_id",
    "turn",
    "decision_index",
    "decision_type",
    "mode",
    "my_player_index",
    "chosen_line_id",
    "chosen_line_score",
    "best_candidate_score",
    "regret",
    "score_margin",
    "num_candidates",
    "selector_source",
    "selector_reasoning",
    "origin",
    "timestamp",
)

_SNAPSHOT_UI_DROP = {
    "analysis_state_json",
    "brief_state_json",
    "brief_state",
}


def _slim_candidate_for_ui(cand: dict[str, Any]) -> dict[str, Any]:
    """Keep line identity + moves; drop per-candidate search/feature snapshots."""
    return {
        "line_id": cand.get("line_id"),
        "rank": cand.get("rank"),
        "score": cand.get("score"),
        "chosen": bool(cand.get("chosen")),
        "moves": cand.get("moves") or [],
    }


def _slim_search_decision_for_ui(dec: Any) -> Optional[dict[str, Any]]:
    if not isinstance(dec, dict):
        return None
    return {k: dec.get(k) for k in _SEARCH_DECISION_UI_KEYS if k in dec}


def _analysis_decision_detail(
    memory: Memory,
    *,
    game_id: str,
    turn: int,
    decision_index: int,
    include_state: bool = True,
) -> dict[str, Any]:
    """Bundle for the Analysis UI: load_decision_bundle + episodic row.

    ``include_state=False`` skips shipping ``analysis_state`` (the full GameState
    dump). Open-on-board fetches that separately via ``/analysis/checkpoint``.
    Candidates are always slimmed: search_state / features / resolved_state are
    not needed to list or replay a line.
    """
    from .analysis import counterfactual as cf

    bundle = cf.load_decision_bundle(
        memory,
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        candidate_detail=False,
        include_analysis_state=include_state,
    )
    episodic = memory.get_episodic_decision(
        game_id=game_id, turn=turn, decision_index=decision_index,
    )
    if episodic is not None:
        episodic = dict(episodic)
        episodic["move"] = _json_maybe(episodic.get("move_json"))
        episodic.pop("move_json", None)

    snap = bundle.get("snapshot")
    analysis_state = None
    replay = None
    if include_state:
        raw_state = snap.get("analysis_state_json") if isinstance(snap, dict) else None
        if raw_state:
            parsed = _json_maybe(raw_state)
            if isinstance(parsed, dict):
                replay = parsed.get("replay")
                analysis_state = parsed
        status = cf.snapshot_status(bundle)
    elif isinstance(snap, dict) and snap.get("has_analysis_state"):
        status = cf.STATUS_OK
    else:
        status = cf.snapshot_status(bundle)
    seat = 0
    dec = bundle.get("search_decision") or {}
    if dec.get("my_player_index") is not None:
        seat = int(dec["my_player_index"])

    snap_out = None
    if isinstance(snap, dict):
        snap_out = {k: v for k, v in snap.items() if k not in _SNAPSHOT_UI_DROP}
        snap_out["analysis_state"] = analysis_state
        snap_out["analysis_state_json"] = None

    return {
        "game_id": game_id,
        "turn": turn,
        "decision_index": decision_index,
        "seat": seat,
        "snapshot_status": status,
        "episodic": episodic,
        "search_decision": _slim_search_decision_for_ui(bundle.get("search_decision")),
        "snapshot": snap_out,
        "root_state_hash": (snap or {}).get("root_state_hash") if snap else None,
        "replay": replay,
        "candidates": [_slim_candidate_for_ui(c) for c in (bundle.get("candidates") or [])],
        "reasoner": bundle.get("reasoner"),
        "game": bundle.get("game"),
        "weight_version": {
            "id": (bundle.get("weight_version") or {}).get("id"),
            "label": (bundle.get("weight_version") or {}).get("label"),
        } if bundle.get("weight_version") else None,
    }


def _analysis_checkpoint(
    memory: Memory,
    *,
    game_id: str,
    turn: int,
    decision_index: int,
) -> dict[str, Any]:
    """Just the restore blob for Open on Board — no candidate / CF payloads."""
    from .analysis import counterfactual as cf

    with memory._connect() as conn:
        snap = conn.execute(
            """
            SELECT analysis_state_json, root_state_hash
            FROM decision_snapshots
            WHERE game_id=? AND turn=? AND decision_index=?
            ORDER BY id DESC LIMIT 1
            """,
            (game_id, turn, decision_index),
        ).fetchone()
        dec = conn.execute(
            """
            SELECT my_player_index FROM search_decisions
            WHERE game_id=? AND turn=? AND decision_index=?
            ORDER BY id DESC LIMIT 1
            """,
            (game_id, turn, decision_index),
        ).fetchone()
    analysis_state = None
    replay = None
    root_hash = None
    status = cf.STATUS_NO_SNAPSHOT
    if snap is not None:
        root_hash = snap["root_state_hash"]
        parsed = _json_maybe(snap["analysis_state_json"])
        if isinstance(parsed, dict):
            analysis_state = parsed
            replay = parsed.get("replay")
            if isinstance(replay, dict) and replay.get("supported") is False:
                status = cf.STATUS_UNSUPPORTED
            else:
                status = cf.STATUS_OK
    seat = 0
    if dec is not None and dec["my_player_index"] is not None:
        seat = int(dec["my_player_index"])
    return {
        "game_id": game_id,
        "turn": turn,
        "decision_index": decision_index,
        "seat": seat,
        "root_state_hash": root_hash,
        "replay": replay,
        "snapshot_status": status,
        "analysis_state": analysis_state,
    }


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


@app.get("/card_stats")
async def card_stats_endpoint(min_plays: int = 20) -> dict:
    """Per-card aggregate statistics (storage doc §3). WPA omitted for now."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return _memory.card_stats_report(min_plays=min_plays)


# ── Post-game analysis UI ─────────────────────────────────────────────────────


@app.get("/analysis/db-status")
async def analysis_db_status() -> dict:
    """Self-play / counterfactual readiness checks for agent_memory.db."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    from .analysis import wpa_report

    with _memory._connect() as conn:
        return wpa_report.validate_db_readiness(conn)


@app.get("/analysis/decisions")
async def analysis_list_decisions(
    game_id: str | None = None,
    replay_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Paginated decision list for the Godot Analysis scene."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    rows = _memory.list_decisions(
        game_id=game_id,
        replay_only=replay_only,
        limit=limit,
        offset=offset,
    )
    return {"decisions": rows, "count": len(rows), "limit": limit, "offset": offset}


@app.get("/analysis/decision")
async def analysis_get_decision(
    game_id: str,
    turn: int,
    decision_index: int,
    include_state: bool = False,
) -> dict:
    """Decision bundle for the Analysis UI.

    Default omits ``analysis_state`` (full GameState dump). Pass
    ``include_state=true`` or GET ``/analysis/checkpoint`` when restoring
    the board.
    """
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    detail = _analysis_decision_detail(
        _memory,
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        include_state=include_state,
    )
    if (
        detail.get("episodic") is None
        and detail.get("search_decision") is None
        and detail.get("snapshot") is None
    ):
        raise HTTPException(status_code=404, detail="Decision not found")
    return detail


@app.get("/analysis/checkpoint")
async def analysis_get_checkpoint(
    game_id: str,
    turn: int,
    decision_index: int,
) -> dict:
    """Restore blob only: analysis_state + hash. Used by Open on Board."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    payload = _analysis_checkpoint(
        _memory,
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
    )
    if payload.get("analysis_state") is None:
        raise HTTPException(status_code=404, detail="No analysis_state for this decision")
    return payload


@app.post("/analysis/counterfactual")
async def analysis_counterfactual(body: AnalysisDecisionKey) -> dict:
    """Run outcome rollout (default) or same-turn offline counterfactual."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    from .analysis import counterfactual as cf

    try:
        result = cf.analyze_decision(
            _memory,
            game_id=body.game_id,
            turn=body.turn,
            decision_index=body.decision_index,
            persist=body.persist,
            mode=body.mode,
            preset=body.preset,
            future_player_turns=body.future_player_turns,
            target=body.target,
            force_same_turn=body.force_same_turn,
            budget=body.budget,
        )
    except Exception as exc:
        logger.exception("Counterfactual analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "result": result,
        "markdown": cf.render_markdown(result),
    }


@app.get("/analysis/counterfactual-runs")
async def analysis_counterfactual_runs(
    game_id: str,
    turn: int,
    decision_index: int,
    limit: int = 20,
    include_result: bool = False,
) -> dict:
    """List persisted CF / rollout runs for a decision (newest first).

    Results are omitted by default; fetch one run via
    ``GET /analysis/counterfactual-runs/{run_id}``.
    """
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    rows = _memory.list_counterfactual_runs(
        game_id=game_id,
        turn=turn,
        decision_index=decision_index,
        limit=limit,
        include_result=include_result,
    )
    return {"runs": rows, "count": len(rows)}


@app.get("/analysis/counterfactual-runs/{run_id}")
async def analysis_counterfactual_run(run_id: int) -> dict:
    """One persisted CF / rollout run including the full result tree."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    row = _memory.get_counterfactual_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@app.post("/analysis/failure-report")
async def analysis_failure_report(body: FailureReportRequest) -> dict:
    """Classify failure modes; optionally run (or reuse) a counterfactual."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    from .analysis import counterfactual as cf
    from .analysis import failure_modes as fm

    try:
        bundle = cf.load_decision_bundle(
            _memory,
            game_id=body.game_id,
            turn=body.turn,
            decision_index=body.decision_index,
        )
        cf_result = body.counterfactual_result
        if cf_result is None and body.with_counterfactual:
            cf_result = cf.analyze_decision(
                _memory,
                game_id=body.game_id,
                turn=body.turn,
                decision_index=body.decision_index,
                persist=body.persist,
                mode=body.mode,
                preset=body.preset,
                future_player_turns=body.future_player_turns,
                target=body.target,
                force_same_turn=body.force_same_turn,
                budget=body.budget,
            )
        report = fm.classify_with_counterfactual(bundle, cf_result)
    except Exception as exc:
        logger.exception("Failure-report analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "report": report,
        "markdown": fm.render_markdown(report),
        "counterfactual": cf_result,
    }


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


@app.post("/card_event")
async def card_event_endpoint(body: CardEventRequest) -> dict:
    """
    Godot calls this on each card lifecycle event (drawn/played/discarded/died/
    mulliganed/scored/left_in_hand_at_end/in_opening_hand). The base
    definition_id is stamped engine-side onto every event (doc §3 join-key note);
    it is never reverse-engineered from instance_id here.
    """
    if _memory is None:
        return {"status": "no-op"}
    try:
        _memory.record_card_event(
            game_id=body.game_id,
            turn=body.turn,
            card_def_id=body.card_def_id,
            event=body.event,
            instance_id=body.instance_id,
            my_player_index=body.my_player_index,
            energy_spent=body.energy_spent,
            breakdown_delta=body.breakdown_delta,
        )
    except ValueError as exc:
        logger.warning("Card event rejected: %s", exc)
        return {"status": "rejected", "reason": str(exc)}
    except Exception as exc:
        logger.warning("Card event record failed: %s", exc)
    return {"status": "ok"}


@app.post("/turn_snapshot")
async def turn_snapshot_endpoint(body: TurnSnapshotRequest) -> dict:
    """Godot posts one BriefState pulse at end-of-Ending-Phase (before turn++)."""
    if _memory is None:
        return {"status": "no-op"}
    try:
        capture_mod.capture_turn_snapshot(
            memory=_memory,
            game_id=body.game_id,
            turn=body.turn,
            brief_state=body.brief_state,
            my_player_index=body.my_player_index,
            turn_player_index=body.turn_player_index,
        )
    except Exception as exc:
        logger.warning("Turn snapshot record failed: %s", exc)
        return {"status": "error"}
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
        "goals_enabled": _goals_enabled and not _argmax_enabled and not _reasoner_enabled,
        "reasoner_enabled": _reasoner_enabled,
        "pipeline": _pipeline_mode,
    }


@app.post("/goals")
async def goals_endpoint(request: GoalsRequest) -> dict:
    """Pre-search handshake. Returns this turn's compiled goal overlay so the
    engine can build TurnSearch under the biased weights. No-op (empty overlay)
    when goals are disabled, so the engine can call it unconditionally."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    brief_state = request.brief_state.model_dump()
    game_id = request.game_id
    if not (_goals_enabled and not _argmax_enabled):
        return {"overlay": {}}
    # Install state so the strategist's read tools (evaluate_position,
    # get_card_detail, …) resolve against this position.
    skill_module.set_state(brief_state)
    try:
        overlay, _goal_set = await build_goal_overlay(
            brief_state=brief_state,
            game_id=game_id,
            memory=_memory,
            eval_metrics={},
            candidate_lines=request.candidate_lines,
            search_stats=request.search_stats,
        )
    except Exception as exc:  # noqa: BLE001 — never fail the turn on a goal error
        logger.warning("Goal overlay (handshake) failed (%s); empty overlay", exc)
        return {"overlay": {}}
    return {"overlay": overlay.to_dict()}


def _capture_reasoner_row(
    *,
    game_id: str,
    turn: int,
    brief_state: dict[str, Any],
    root_state_hash: Optional[str],
    telemetry: dict[str, Any],
    emit: Any,
    committed_line: Optional[dict[str, Any]],
    eval_metrics: Optional[dict[str, Any]] = None,
    decision_index: Optional[int] = None,
) -> None:
    """Best-effort SQL write for one /reason call."""
    if _memory is None or not hasattr(_memory, "record_reasoner_decision"):
        return
    try:
        # When a line commit also wrote decisions/*, use that allocated index.
        # Otherwise point at the upcoming /decision index (goals / fallback).
        if decision_index is None:
            decision_index = _memory._decision_counters.get(game_id, 0)
        capture_mod.capture_reasoner_decision(
            memory=_memory,
            game_id=game_id,
            turn=turn,
            decision_index=decision_index,
            root_state_hash=root_state_hash,
            telemetry=telemetry,
            chosen_line_id=getattr(emit, "chosen_line_id", None),
            committed_line=committed_line,
            rationale=getattr(emit, "rationale", None),
            eval_metrics=eval_metrics,
        )
    except Exception as exc:  # noqa: BLE001 — never fail /reason on capture
        logger.warning("Reasoner decision capture failed: %s", exc)


@app.post("/reason")
async def reason_endpoint(request: ReasonRequest) -> dict:
    """Run the bounded Phase-3 Reasoner before the main turn search."""
    if _memory is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    turn = int(request.brief_state.turn_number)
    game_id = request.game_id
    brief_state = request.brief_state.model_dump()
    key = _reasoner_overlay_key(game_id, brief_state)
    if not request.root_state_hash:
        _reasoner_overlays.pop(key, None)
        emit = empty_reasoner_emit(turn, "fallback: missing root state hash")
        telemetry = {"fallback_reason": "missing_root_state_hash", "terminal_kind": emit.kind}
        _capture_reasoner_row(
            game_id=game_id,
            turn=turn,
            brief_state=brief_state,
            root_state_hash="",
            telemetry=telemetry,
            emit=emit,
            committed_line=None,
        )
        return {
            **emit.model_dump(),
            "overlay": {},
            "committed_line": None,
            "root_state_hash": "",
            "telemetry": telemetry,
        }
    if not _reasoner_enabled:
        _reasoner_overlays.pop(key, None)
        emit = empty_reasoner_emit(turn, "fallback: reasoner disabled")
        telemetry = {"fallback_reason": "reasoner_disabled", "terminal_kind": emit.kind}
        _capture_reasoner_row(
            game_id=game_id,
            turn=turn,
            brief_state=brief_state,
            root_state_hash=request.root_state_hash,
            telemetry=telemetry,
            emit=emit,
            committed_line=None,
        )
        return {
            **emit.model_dump(),
            "overlay": {},
            "committed_line": None,
            "root_state_hash": request.root_state_hash,
            "telemetry": telemetry,
        }

    skill_module.set_state(brief_state)
    skill_module.set_history_context(_memory, game_id)
    eval_metrics: dict = {}
    try:
        emit, committed_line, telemetry = await run_reasoner(
            brief_state=brief_state,
            game_id=game_id,
            memory=_memory,
            eval_metrics=eval_metrics,
            candidate_lines=request.candidate_lines,
            search_stats=request.search_stats,
            root_state_hash=request.root_state_hash,
        )
    except Exception as exc:  # noqa: BLE001 — fail safe to base search
        logger.warning("Reasoner failed (%s); base-profile search", exc)
        emit = empty_reasoner_emit(turn, "fallback: reasoner failure")
        committed_line = None
        telemetry = {
            "fallback_reason": "reasoner_failure",
            "error": str(exc),
            "terminal_kind": emit.kind,
        }

    if emit.kind == "line":
        logger.info(
            "Reasoner output: kind=line confidence=%s line=%s moves=%s | %s",
            emit.confidence,
            emit.chosen_line_id or "missing",
            " ; ".join((committed_line or {}).get("moves", []) or []),
            emit.rationale,
        )
    else:
        goal_ids = [goal.id for goal in (emit.goal_set.goals if emit.goal_set else [])]
        logger.info(
            "Reasoner output: kind=goals confidence=%s goals=%s | %s",
            emit.confidence,
            goal_ids,
            emit.rationale,
        )

    overlay = compile_goals(emit.goal_set) if emit.kind == "goals" and emit.goal_set else None
    if overlay is not None and not overlay.is_empty():
        _reasoner_overlays[key] = (overlay, emit.goal_set)
    else:
        _reasoner_overlays.pop(key, None)

    # Reasoner line commits skip /decision on the Godot side — persist the same
    # episodic / snapshot / search rows here so Analysis UI can list them.
    allocated_index: Optional[int] = None
    if (
        emit.kind == "line"
        and isinstance(committed_line, dict)
        and committed_line.get("moves")
        and _memory is not None
    ):
        allocated_index = capture_mod.capture_reasoner_line_decision(
            memory=_memory,
            brief_state=brief_state,
            request=request,
            committed_line=committed_line,
            rationale=getattr(emit, "rationale", None),
            eval_metrics=eval_metrics,
            search_enabled=_search_enabled,
            data_origin=_data_origin,
            capture_seat=_capture_seat,
            weight_resolver=_resolve_weight_version,
        )

    _capture_reasoner_row(
        game_id=game_id,
        turn=turn,
        brief_state=brief_state,
        root_state_hash=request.root_state_hash,
        telemetry=telemetry,
        emit=emit,
        committed_line=committed_line,
        eval_metrics=eval_metrics,
        decision_index=allocated_index,
    )
    return {
        **emit.model_dump(),
        "overlay": overlay.to_dict() if overlay is not None else {},
        "committed_line": committed_line,
        "root_state_hash": request.root_state_hash,
        "telemetry": telemetry,
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
