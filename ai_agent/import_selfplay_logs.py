"""
Riftbound AI Agent — offline self-play log importer.

Replays a capture log produced by the engine's offline self-play mode
(``RIFTBOUND_SELFPLAY_CAPTURE``) into the SQLite tuning database, writing the
exact same rows the live ``/decision`` + event endpoints would have written —
but without running the FastAPI server during the games.

Why this exists
---------------
In argmax self-play the Python server does no LLM work: it only (1) picks the
highest-scoring searched line (a pure function of scores the engine already
computed) and (2) writes SQL. Every decision carries candidate lines, so the
selection is reproduced here by the SAME ``_argmax_line`` the server uses, and
the SQL writes go through the SAME ``ai_agent.capture`` helpers. The engine
therefore needs no per-move HTTP round-trip; it appends one JSON object per
server-bound payload to the log, and this script flushes them to the DB
afterward.

Log format (JSON Lines; one object per line, in emission order)
---------------------------------------------------------------
  {"kind": "decision",        "request": <DecisionRequest payload>}
  {"kind": "outcome",         "game_id", "accepted", "rejection_reason"}
  {"kind": "decision_metrics","game_id", "turn", "decision_type", "latency_ms",
                              "rejection_retries", "heuristic_fallback", "accepted"}
  {"kind": "card_event",      "game_id", "turn", "card_def_id", "event", ...}
  {"kind": "opponent_action", "game_id", "turn", "action"}
  {"kind": "turn_snapshot",   "game_id", "turn", "brief_state", ...}
  {"kind": "game_over",       "game_id", "winner_index", "my_player_index", ...}

Usage
-----
  python -m ai_agent.import_selfplay_logs out/selfplay_capture.jsonl \
      --db ai_agent/selfplay.db --origin self_play [--capture-seat 0]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Optional

from . import capture as capture_mod
from .agent import _PASS_DECISION, _argmax_line
from .memory import Memory
from .schemas import Decision, DecisionRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("ai_agent.import_selfplay_logs")


# ── Config / weight version resolution (mirrors main.py lifespan) ─────────────


def _load_scoring_profile() -> Optional[str]:
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


def _git_sha() -> Optional[str]:
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


def _make_weight_resolver(memory: Memory, startup_id: Optional[int], git_sha: Optional[str]):
    """Map a request's scoring-profile JSON to its weight_versions.id (cached)."""
    cache: dict[str, int] = {}

    def resolve(profile_json: Optional[str]) -> Optional[int]:
        if not profile_json:
            return startup_id
        cached = cache.get(profile_json)
        if cached is not None:
            return cached
        try:
            wv = memory.record_weight_version(profile_json=profile_json, git_sha=git_sha)
        except Exception as exc:
            logger.warning("Per-request weight version resolve failed: %s", exc)
            return startup_id
        cache[profile_json] = wv
        return wv

    return resolve


# ── Decision reconstruction (mirrors choose_line argmax_only=True) ────────────


def _decide_argmax(request: DecisionRequest) -> Decision:
    """Reproduce the server's argmax selection for a logged decision request.

    Equivalent to ``choose_line(..., argmax_only=True)``: returns the
    highest-scoring playable line, or a pass when no line is playable. Using the
    server's own ``_argmax_line`` guarantees the imported rows are byte-identical
    to a live run.
    """
    if not request.candidate_lines:
        return _PASS_DECISION
    return _argmax_line(request.candidate_lines, source="argmax")


# ── Record dispatch ───────────────────────────────────────────────────────────


def import_log(
    log_path: Path,
    *,
    db_path: Optional[Path],
    data_origin: str,
    capture_seat: Optional[int],
) -> dict:
    memory = Memory(db_path=db_path) if db_path is not None else Memory()

    git_sha = _git_sha()
    startup_weight_id: Optional[int] = None
    profile_json = _load_scoring_profile()
    if profile_json is not None:
        try:
            startup_weight_id = memory.record_weight_version(
                profile_json=profile_json, git_sha=git_sha
            )
        except Exception as exc:
            logger.warning("Startup weight version record failed: %s", exc)
    weight_resolver = _make_weight_resolver(memory, startup_weight_id, git_sha)

    counts: dict[str, int] = {}
    errors = 0
    parity_mismatches = 0

    with open(log_path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("Line %d: bad JSON (%s); skipping", line_no, exc)
                errors += 1
                continue
            kind = rec.get("kind", "")
            counts[kind] = counts.get(kind, 0) + 1
            try:
                if kind == "decision":
                    request = DecisionRequest.model_validate(rec["request"])
                    decision = _decide_argmax(request)
                    # Parity guard: the engine recorded which line it played; it
                    # must equal the server's argmax choice or the offline game
                    # trajectory diverged from a live run.
                    logged_choice = rec.get("chosen_line_id", "__unset__")
                    if logged_choice != "__unset__" and logged_choice != decision.chosen_line_id:
                        parity_mismatches += 1
                        logger.warning(
                            "Line %d: argmax parity mismatch (engine=%s importer=%s)",
                            line_no, logged_choice, decision.chosen_line_id,
                        )
                    capture_mod.capture_decision(
                        memory=memory,
                        brief_state=request.brief_state.model_dump(),
                        request=request,
                        decision=decision,
                        eval_metrics={},
                        search_enabled=True,
                        data_origin=data_origin,
                        capture_seat=capture_seat,
                        weight_resolver=weight_resolver,
                    )
                elif kind == "outcome":
                    capture_mod.capture_outcome(
                        memory=memory,
                        game_id=rec["game_id"],
                        accepted=bool(rec.get("accepted", True)),
                        rejection_reason=rec.get("rejection_reason") or None,
                    )
                elif kind == "decision_metrics":
                    capture_mod.capture_client_decision_metrics(
                        memory=memory,
                        game_id=rec["game_id"],
                        turn=int(rec.get("turn", 0)),
                        decision_type=rec.get("decision_type"),
                        latency_ms=int(rec.get("latency_ms", 0)),
                        rejection_retries=int(rec.get("rejection_retries", 0)),
                        heuristic_fallback=bool(rec.get("heuristic_fallback", False)),
                        accepted=rec.get("accepted"),
                    )
                elif kind == "card_event":
                    capture_mod.capture_card_event(
                        memory=memory,
                        game_id=rec["game_id"],
                        turn=int(rec.get("turn", 0)),
                        card_def_id=rec["card_def_id"],
                        event=rec["event"],
                        instance_id=rec.get("instance_id"),
                        my_player_index=rec.get("my_player_index"),
                        energy_spent=int(rec.get("energy_spent", 0)),
                        breakdown_delta=rec.get("breakdown_delta"),
                    )
                elif kind == "opponent_action":
                    capture_mod.capture_opponent_action(
                        memory=memory,
                        game_id=rec["game_id"],
                        turn=int(rec.get("turn", 0)),
                        action=rec["action"],
                    )
                elif kind == "turn_snapshot":
                    capture_mod.capture_turn_snapshot(
                        memory=memory,
                        game_id=rec["game_id"],
                        turn=int(rec.get("turn", 0)),
                        brief_state=rec.get("brief_state") or {},
                        my_player_index=rec.get("my_player_index"),
                        turn_player_index=rec.get("turn_player_index"),
                    )
                elif kind == "game_over":
                    summary = capture_mod.capture_game_over(
                        memory=memory,
                        game_id=rec["game_id"],
                        winner_index=int(rec["winner_index"]),
                        my_player_index=int(rec["my_player_index"]),
                        my_score=int(rec.get("my_score", 0)),
                        opp_score=int(rec.get("opp_score", 0)),
                        total_turns=int(rec.get("total_turns", 0)),
                        first_player_index=int(rec.get("first_player_index", -1)),
                        seed=rec.get("seed"),
                    )
                    logger.info(
                        "Game over: game=%s outcome=%s",
                        rec["game_id"], summary.get("outcome"),
                    )
                else:
                    logger.warning("Line %d: unknown kind %r; skipping", line_no, kind)
                    errors += 1
            except Exception as exc:
                logger.warning("Line %d (%s): import failed: %s", line_no, kind, exc)
                errors += 1

    result = {
        "records": dict(counts),
        "errors": errors,
        "parity_mismatches": parity_mismatches,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Import offline self-play capture logs into SQLite.")
    parser.add_argument("log", type=Path, help="Path to the JSONL capture log (e.g. out/selfplay_capture.jsonl).")
    parser.add_argument("--db", type=Path, default=None,
                        help="SQLite DB path (default: RIFTBOUND_DB_PATH or ai_agent/agent_memory.db).")
    parser.add_argument("--origin", default=None,
                        help="Provenance tag for captured rows (default: RIFTBOUND_DATA_ORIGIN or 'self_play').")
    parser.add_argument("--capture-seat", type=int, choices=(0, 1), default=None,
                        help="Persist tuning rows for only this seat's decisions (default: both seats / env).")
    args = parser.parse_args()

    if not args.log.exists():
        parser.error(f"log file not found: {args.log}")

    db_path = args.db
    if db_path is None:
        env_db = os.environ.get("RIFTBOUND_DB_PATH", "").strip()
        db_path = Path(env_db) if env_db else None

    data_origin = args.origin or os.environ.get("RIFTBOUND_DATA_ORIGIN", "self_play").strip() or "self_play"

    capture_seat = args.capture_seat
    if capture_seat is None:
        env_seat = os.environ.get("RIFTBOUND_CAPTURE_SEAT", "").strip()
        if env_seat in ("0", "1"):
            capture_seat = int(env_seat)

    logger.info("Importing %s → db=%s origin=%s capture_seat=%s",
                args.log, db_path or "(default)", data_origin,
                "both" if capture_seat is None else capture_seat)

    result = import_log(
        args.log,
        db_path=db_path,
        data_origin=data_origin,
        capture_seat=capture_seat,
    )

    logger.info("Imported records: %s", result["records"])
    if result["parity_mismatches"]:
        logger.warning("Argmax parity mismatches: %d", result["parity_mismatches"])
    if result["errors"]:
        logger.warning("Import completed with %d error(s).", result["errors"])
    else:
        logger.info("Import completed cleanly.")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
