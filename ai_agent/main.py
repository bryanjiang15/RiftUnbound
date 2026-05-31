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

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from pydantic import BaseModel

from . import skills as skill_module
from .agent import decide, _INPUT_LOG_PATH, _LOG_INPUTS
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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _memory, _decision_logger
    _memory = Memory()
    _decision_logger = DecisionLogger()
    _decision_logger.clear()          # fresh log on every server start
    if _LOG_INPUTS:
        _INPUT_LOG_PATH.write_text(
            f"Riftbound AI Agent — Input Log\nStarted: "
            f"{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            + "═" * 72 + "\n",
            encoding="utf-8",
        )
    logger.info("Riftbound AI agent service started.")
    logger.info("OpenAI API key: %s", "set" if os.environ.get("OPENAI_API_KEY") else "NOT SET")
    logger.info("Input logging: %s", "ENABLED → agent_inputs.log" if _LOG_INPUTS else "disabled")
    yield
    logger.info("Riftbound AI agent service shutting down.")


app = FastAPI(
    title="Riftbound AI Agent",
    description="Python reasoning agent for the Riftbound TCG simulator.",
    version="1.0.0",
    lifespan=_lifespan,
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

    # Run reasoning loop
    decision = await decide(
        brief_state=brief_state,
        game_id=game_id,
        memory=_memory,
        rejection_context=rejection_ctx,
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


class OpponentActionRequest(BaseModel):
    game_id: str
    turn: int
    action: str


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
    try:
        _memory.record_game_outcome(
            game_id=body.game_id,
            outcome=outcome,
            my_score=body.my_score,
            opp_score=body.opp_score,
            turns_played=body.total_turns,
        )
    except Exception as exc:
        logger.warning("Game outcome record failed: %s", exc)
    logger.info(
        "Game over: game=%s outcome=%s score=%d-%d turns=%d",
        body.game_id, outcome, body.my_score, body.opp_score, body.total_turns,
    )
    return {"status": "ok", "outcome": outcome}


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


# ── Debug / read-skill proxy endpoints ────────────────────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


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
