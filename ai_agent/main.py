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

from . import skills as skill_module
from .agent import decide
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
    logger.info("Riftbound AI agent service started.")
    logger.info("OpenAI API key: %s", "set" if os.environ.get("OPENAI_API_KEY") else "NOT SET")
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


# ── Outcome reporting (called by Godot after applying / rejecting) ────────────


@app.post("/outcome")
async def outcome_endpoint(body: dict) -> dict:
    """
    Godot calls this after applying or rejecting a move.
    Body: { game_id, accepted: bool, rejection_reason: str|null, outcome_summary: str|null }
    This is best-effort — the agent continues even if this is never called.
    """
    if _memory is None:
        return {"status": "no-op"}
    logger.info("Outcome: %s", body)
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
