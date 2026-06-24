"""
Riftbound AI Agent — Episodic Memory

Two persistence layers:

  Memory (SQLite)     — structured append-only event log, used for context
                        injection and replay.  One row per decision.

  DecisionLogger      — human-readable JSONL file written alongside every
                        decision so a reviewer can open it and see exactly what
                        the agent reasoned and did each turn, without querying
                        SQLite.  File: agent_decisions_<game_id>.jsonl

Cross-game knowledge is intentionally out of scope for now.
Godot assigns a unique game_session_id per match (see GameState.game_session_id);
memory queries are scoped to that id, not player names alone.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path(__file__).parent / "agent_memory.db"

# Columns in the decisions table
_DDL = """
CREATE TABLE IF NOT EXISTS decisions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          TEXT    NOT NULL,
    turn             INTEGER NOT NULL,
    decision_index   INTEGER NOT NULL,
    decision_type    TEXT    NOT NULL,
    brief_state_hash TEXT    NOT NULL,
    reasoning        TEXT    NOT NULL,
    move_json        TEXT    NOT NULL,
    accepted         INTEGER,         -- NULL = unknown, 1 = accepted, 0 = rejected
    rejection_reason TEXT,
    outcome_summary  TEXT,
    timestamp        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_game_turn ON decisions (game_id, turn, decision_index);

CREATE TABLE IF NOT EXISTS opponent_actions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id   TEXT    NOT NULL,
    turn      INTEGER NOT NULL,
    action    TEXT    NOT NULL,
    timestamp TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opp_game ON opponent_actions (game_id, turn);

CREATE TABLE IF NOT EXISTS games (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id      TEXT UNIQUE NOT NULL,
    outcome      TEXT,          -- 'win' | 'loss' | 'draw' | NULL = in progress
    my_score     INTEGER,
    opp_score    INTEGER,
    turns_played INTEGER,
    timestamp    TEXT NOT NULL
);

-- Server-side reliability metrics: one row per produced decision.
CREATE TABLE IF NOT EXISTS decision_eval_metrics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id          TEXT    NOT NULL,
    turn             INTEGER NOT NULL,
    decision_index   INTEGER NOT NULL,
    decision_type    TEXT    NOT NULL,
    model_calls      INTEGER NOT NULL DEFAULT 0,
    tool_rounds      INTEGER NOT NULL DEFAULT 0,
    parse_retries    INTEGER NOT NULL DEFAULT 0,
    legality_retries INTEGER NOT NULL DEFAULT 0,
    fell_back_to_pass INTEGER NOT NULL DEFAULT 0,  -- 1 = returned the safety pass
    latency_ms       INTEGER NOT NULL DEFAULT 0,
    -- Token usage (overall + planner/actor split). One decision may invoke the
    -- planner agent (per-turn, often cached) and the actor/decision agent.
    prompt_tokens             INTEGER NOT NULL DEFAULT 0,
    completion_tokens         INTEGER NOT NULL DEFAULT 0,
    total_tokens              INTEGER NOT NULL DEFAULT 0,
    planner_model_calls       INTEGER NOT NULL DEFAULT 0,
    planner_prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    planner_completion_tokens INTEGER NOT NULL DEFAULT 0,
    planner_total_tokens      INTEGER NOT NULL DEFAULT 0,
    actor_model_calls         INTEGER NOT NULL DEFAULT 0,
    actor_prompt_tokens       INTEGER NOT NULL DEFAULT 0,
    actor_completion_tokens   INTEGER NOT NULL DEFAULT 0,
    actor_total_tokens        INTEGER NOT NULL DEFAULT 0,
    timestamp        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_game ON decision_eval_metrics (game_id, turn, decision_index);

-- Engine-observed metrics reported by Godot (latency as the game sees it, plus
-- rejection retries and whether the AIPlayer fell back to its built-in heuristic).
CREATE TABLE IF NOT EXISTS client_decision_metrics (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id           TEXT    NOT NULL,
    turn              INTEGER NOT NULL,
    decision_type     TEXT,
    latency_ms        INTEGER NOT NULL DEFAULT 0,
    rejection_retries INTEGER NOT NULL DEFAULT 0,
    heuristic_fallback INTEGER NOT NULL DEFAULT 0,
    accepted          INTEGER,                       -- 1 = engine accepted final move
    timestamp         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_client_eval_game ON client_decision_metrics (game_id, turn);

-- One reliability scorecard per finished game (aggregated on /game_over).
CREATE TABLE IF NOT EXISTS game_eval_summary (
    game_id            TEXT PRIMARY KEY,
    decisions          INTEGER NOT NULL DEFAULT 0,
    model_calls_total  INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms     REAL    NOT NULL DEFAULT 0,
    p95_latency_ms     INTEGER NOT NULL DEFAULT 0,
    parse_retry_total  INTEGER NOT NULL DEFAULT 0,
    legality_retry_total INTEGER NOT NULL DEFAULT 0,
    fallback_count     INTEGER NOT NULL DEFAULT 0,
    prompt_tokens_total       INTEGER NOT NULL DEFAULT 0,
    completion_tokens_total   INTEGER NOT NULL DEFAULT 0,
    total_tokens_total        INTEGER NOT NULL DEFAULT 0,
    planner_total_tokens_total INTEGER NOT NULL DEFAULT 0,
    actor_total_tokens_total   INTEGER NOT NULL DEFAULT 0,
    timestamp          TEXT    NOT NULL
);

-- Human evaluation feedback (rubric scores + tags + free-text note).
CREATE TABLE IF NOT EXISTS human_feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id       TEXT    NOT NULL,
    reviewer      TEXT,
    scope         TEXT    NOT NULL DEFAULT 'game',  -- 'game' | 'decision'
    turn          INTEGER,
    decision_index INTEGER,
    strategic     INTEGER,
    tactical      INTEGER,
    resource      INTEGER,
    rules         INTEGER,
    overall       INTEGER,
    tags          TEXT,                              -- JSON array
    note          TEXT,
    timestamp     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_game ON human_feedback (game_id);

-- Lightweight per-move sentiment (thumbs up/down/neutral) collected live during
-- play. An ignored move simply has no row, which is how "ignored" is told apart
-- from an explicit "neutral" rating.
CREATE TABLE IF NOT EXISTS move_feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     TEXT    NOT NULL,
    turn        INTEGER,
    move_seq    INTEGER,                 -- client-side index of the AI move
    sentiment   TEXT    NOT NULL,        -- 'like' | 'neutral' | 'dislike'
    move_desc   TEXT,
    reviewer    TEXT,
    timestamp   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_move_feedback_game ON move_feedback (game_id, turn);
"""

# Maximum number of recent events (own decisions + opponent actions, merged) to inject into context
TIMELINE_SLICE_SIZE = 16


class Memory:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._decision_counters: dict[str, int] = {}
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Add columns introduced after a DB was first created.

        ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so token /
        per-stage columns added later must be backfilled with ALTER TABLE on
        databases created by an earlier version.
        """
        new_columns = {
            "decision_eval_metrics": [
                "prompt_tokens INTEGER NOT NULL DEFAULT 0",
                "completion_tokens INTEGER NOT NULL DEFAULT 0",
                "total_tokens INTEGER NOT NULL DEFAULT 0",
                "planner_model_calls INTEGER NOT NULL DEFAULT 0",
                "planner_prompt_tokens INTEGER NOT NULL DEFAULT 0",
                "planner_completion_tokens INTEGER NOT NULL DEFAULT 0",
                "planner_total_tokens INTEGER NOT NULL DEFAULT 0",
                "actor_model_calls INTEGER NOT NULL DEFAULT 0",
                "actor_prompt_tokens INTEGER NOT NULL DEFAULT 0",
                "actor_completion_tokens INTEGER NOT NULL DEFAULT 0",
                "actor_total_tokens INTEGER NOT NULL DEFAULT 0",
            ],
            "game_eval_summary": [
                "prompt_tokens_total INTEGER NOT NULL DEFAULT 0",
                "completion_tokens_total INTEGER NOT NULL DEFAULT 0",
                "total_tokens_total INTEGER NOT NULL DEFAULT 0",
                "planner_total_tokens_total INTEGER NOT NULL DEFAULT 0",
                "actor_total_tokens_total INTEGER NOT NULL DEFAULT 0",
            ],
        }
        for table, columns in new_columns.items():
            existing = {
                row["name"]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column_def in columns:
                name = column_def.split()[0]
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Writing ───────────────────────────────────────────────────────────────

    def record(
        self,
        *,
        game_id: str,
        turn: int,
        decision_type: str,
        brief_state: dict,
        reasoning: str,
        move: dict,
        accepted: Optional[bool] = None,
        rejection_reason: Optional[str] = None,
        outcome_summary: Optional[str] = None,
    ) -> int:
        """Append a decision record.  Returns the auto-generated row id."""
        decision_index = self._next_decision_index(game_id)
        brief_hash = _hash_dict(brief_state)
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO decisions
                  (game_id, turn, decision_index, decision_type,
                   brief_state_hash, reasoning, move_json,
                   accepted, rejection_reason, outcome_summary, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    decision_index,
                    decision_type,
                    brief_hash,
                    reasoning,
                    json.dumps(move),
                    (1 if accepted else 0) if accepted is not None else None,
                    rejection_reason,
                    outcome_summary,
                    now,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def update_acceptance(self, row_id: int, accepted: bool, rejection_reason: Optional[str] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE decisions SET accepted=?, rejection_reason=? WHERE id=?",
                (1 if accepted else 0, rejection_reason, row_id),
            )

    def update_acceptance_by_game(self, game_id: str, accepted: bool, rejection_reason: Optional[str] = None) -> None:
        """Update the most recent unresolved decision for a game. Called via /outcome."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE decisions SET accepted=?, rejection_reason=?
                WHERE id = (
                    SELECT id FROM decisions
                    WHERE game_id=? AND accepted IS NULL
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (1 if accepted else 0, rejection_reason, game_id),
            )

    def update_outcome(self, row_id: int, outcome_summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE decisions SET outcome_summary=? WHERE id=?",
                (outcome_summary, row_id),
            )

    def record_opponent_action(self, *, game_id: str, turn: int, action: str) -> None:
        """Append a visible opponent action. Called via /opponent_action."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO opponent_actions (game_id, turn, action, timestamp) VALUES (?,?,?,?)",
                (game_id, turn, action, now),
            )

    def record_game_outcome(
        self,
        *,
        game_id: str,
        outcome: str,
        my_score: int,
        opp_score: int,
        turns_played: int,
    ) -> None:
        """Upsert a completed game record. Called via /game_over."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO games (game_id, outcome, my_score, opp_score, turns_played, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    outcome=excluded.outcome,
                    my_score=excluded.my_score,
                    opp_score=excluded.opp_score,
                    turns_played=excluded.turns_played,
                    timestamp=excluded.timestamp
                """,
                (game_id, outcome, my_score, opp_score, turns_played, now),
            )

    # ── Reading ───────────────────────────────────────────────────────────────

    def opponent_actions_text(self, game_id: str, n: int = 8) -> str:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT turn, action FROM opponent_actions WHERE game_id=? ORDER BY id DESC LIMIT ?",
                (game_id, n),
            ).fetchall()
        if not rows:
            return ""
        return "\n".join(f"  Turn {row['turn']}: {row['action']}" for row in reversed(rows))

    def count_opponent_material_actions(self, game_id: str) -> int:
        """Count visible opponent actions that play a card or use an ability.

        Used by the Planner to decide when to invalidate the per-turn plan cache:
        the plan is regenerated when the opponent plays a card (incl. a reaction)
        or uses an ability, but NOT when they merely pass, move, choose, or end the
        turn. Action strings are produced by AIPlayer.gd's _parse_opponent_command
        ("played ...", "played reaction ...", "used ability ...").
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM opponent_actions WHERE game_id=? "
                "AND (action LIKE 'played %' OR action LIKE 'played reaction %' "
                "OR action LIKE 'used ability %')",
                (game_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def timeline_slice(self, game_id: str, n: int = TIMELINE_SLICE_SIZE) -> str:
        """Return the last n game events — own decisions and opponent actions
        merged into one chronologically ordered context string, oldest first.

        Both tables are written with the same `datetime.now(timezone.utc).isoformat()`
        timestamp format from this process, so ordering by timestamp reflects the
        true turn-by-turn sequence of play.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT turn, timestamp, 'me' AS kind, decision_type,
                       move_json AS detail, accepted, rejection_reason
                FROM decisions WHERE game_id = ?
                UNION ALL
                SELECT turn, timestamp, 'opp' AS kind, NULL AS decision_type,
                       action AS detail, NULL AS accepted, NULL AS rejection_reason
                FROM opponent_actions WHERE game_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (game_id, game_id, n),
            ).fetchall()

        if not rows:
            return ""

        lines: list[str] = [
            "## Game history (chronological — your moves and the opponent's "
            "visible actions, true turn order)"
        ]
        for row in reversed(rows):
            if row["kind"] == "opp":
                lines.append(f"  Turn {row['turn']}: Opponent {row['detail']}")
                continue
            move = json.loads(row["detail"])
            accepted_str = {None: "?", 1: "OK", 0: "REJECTED"}.get(row["accepted"], "?")
            line = (
                f"  Turn {row['turn']} [{row['decision_type']}]: "
                f"You {move.get('action', '?')}({_params_summary(move)}) → {accepted_str}"
            )
            if row["rejection_reason"]:
                line += f" (reason: {row['rejection_reason']})"
            lines.append(line)
        return "\n".join(lines)

    # ── Eval: reliability + human feedback ────────────────────────────────────

    def record_decision_metrics(
        self,
        *,
        game_id: str,
        turn: int,
        decision_index: int,
        decision_type: str,
        metrics: dict,
    ) -> None:
        """Append one server-side reliability row for a produced decision."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decision_eval_metrics
                  (game_id, turn, decision_index, decision_type, model_calls,
                   tool_rounds, parse_retries, legality_retries, fell_back_to_pass,
                   latency_ms, prompt_tokens, completion_tokens, total_tokens,
                   planner_model_calls, planner_prompt_tokens,
                   planner_completion_tokens, planner_total_tokens,
                   actor_model_calls, actor_prompt_tokens,
                   actor_completion_tokens, actor_total_tokens, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    decision_index,
                    decision_type,
                    int(metrics.get("model_calls", 0)),
                    int(metrics.get("tool_rounds", 0)),
                    int(metrics.get("parse_retries", 0)),
                    int(metrics.get("legality_retries", 0)),
                    1 if metrics.get("fell_back_to_pass") else 0,
                    int(metrics.get("latency_ms", 0)),
                    int(metrics.get("prompt_tokens", 0)),
                    int(metrics.get("completion_tokens", 0)),
                    int(metrics.get("total_tokens", 0)),
                    int(metrics.get("planner_model_calls", 0)),
                    int(metrics.get("planner_prompt_tokens", 0)),
                    int(metrics.get("planner_completion_tokens", 0)),
                    int(metrics.get("planner_total_tokens", 0)),
                    int(metrics.get("actor_model_calls", 0)),
                    int(metrics.get("actor_prompt_tokens", 0)),
                    int(metrics.get("actor_completion_tokens", 0)),
                    int(metrics.get("actor_total_tokens", 0)),
                    now,
                ),
            )

    def record_client_decision_metrics(
        self,
        *,
        game_id: str,
        turn: int,
        decision_type: Optional[str],
        latency_ms: int,
        rejection_retries: int,
        heuristic_fallback: bool,
        accepted: Optional[bool],
    ) -> None:
        """Append one engine-observed metrics row (reported by Godot's AIPlayer)."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO client_decision_metrics
                  (game_id, turn, decision_type, latency_ms, rejection_retries,
                   heuristic_fallback, accepted, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    decision_type,
                    int(latency_ms),
                    int(rejection_retries),
                    1 if heuristic_fallback else 0,
                    (1 if accepted else 0) if accepted is not None else None,
                    now,
                ),
            )

    def summarize_game_eval(self, game_id: str) -> dict:
        """Aggregate server-side decision metrics for a game and upsert a scorecard."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT model_calls, parse_retries, legality_retries, "
                "fell_back_to_pass, latency_ms, total_tokens, prompt_tokens, "
                "completion_tokens, planner_total_tokens, actor_total_tokens "
                "FROM decision_eval_metrics "
                "WHERE game_id=? ORDER BY id",
                (game_id,),
            ).fetchall()

        summary = {
            "game_id": game_id,
            "decisions": len(rows),
            "model_calls_total": sum(r["model_calls"] for r in rows),
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0,
            "parse_retry_total": sum(r["parse_retries"] for r in rows),
            "legality_retry_total": sum(r["legality_retries"] for r in rows),
            "fallback_count": sum(r["fell_back_to_pass"] for r in rows),
            "prompt_tokens_total": sum(r["prompt_tokens"] for r in rows),
            "completion_tokens_total": sum(r["completion_tokens"] for r in rows),
            "total_tokens_total": sum(r["total_tokens"] for r in rows),
            "planner_total_tokens_total": sum(r["planner_total_tokens"] for r in rows),
            "actor_total_tokens_total": sum(r["actor_total_tokens"] for r in rows),
        }
        if rows:
            latencies = sorted(r["latency_ms"] for r in rows)
            summary["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1)
            summary["p95_latency_ms"] = _percentile(latencies, 95)

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO game_eval_summary
                  (game_id, decisions, model_calls_total, avg_latency_ms,
                   p95_latency_ms, parse_retry_total, legality_retry_total,
                   fallback_count, prompt_tokens_total, completion_tokens_total,
                   total_tokens_total, planner_total_tokens_total,
                   actor_total_tokens_total, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    decisions=excluded.decisions,
                    model_calls_total=excluded.model_calls_total,
                    avg_latency_ms=excluded.avg_latency_ms,
                    p95_latency_ms=excluded.p95_latency_ms,
                    parse_retry_total=excluded.parse_retry_total,
                    legality_retry_total=excluded.legality_retry_total,
                    fallback_count=excluded.fallback_count,
                    prompt_tokens_total=excluded.prompt_tokens_total,
                    completion_tokens_total=excluded.completion_tokens_total,
                    total_tokens_total=excluded.total_tokens_total,
                    planner_total_tokens_total=excluded.planner_total_tokens_total,
                    actor_total_tokens_total=excluded.actor_total_tokens_total,
                    timestamp=excluded.timestamp
                """,
                (
                    game_id,
                    summary["decisions"],
                    summary["model_calls_total"],
                    summary["avg_latency_ms"],
                    summary["p95_latency_ms"],
                    summary["parse_retry_total"],
                    summary["legality_retry_total"],
                    summary["fallback_count"],
                    summary["prompt_tokens_total"],
                    summary["completion_tokens_total"],
                    summary["total_tokens_total"],
                    summary["planner_total_tokens_total"],
                    summary["actor_total_tokens_total"],
                    now,
                ),
            )
        return summary

    def record_human_feedback(self, *, game_id: str, feedback: dict) -> int:
        """Persist one human-feedback submission. Returns the row id."""
        now = datetime.now(timezone.utc).isoformat()
        tags = feedback.get("tags")
        tags_json = json.dumps(tags) if tags is not None else None
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO human_feedback
                  (game_id, reviewer, scope, turn, decision_index, strategic,
                   tactical, resource, rules, overall, tags, note, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    feedback.get("reviewer"),
                    feedback.get("scope", "game"),
                    feedback.get("turn"),
                    feedback.get("decision_index"),
                    feedback.get("strategic"),
                    feedback.get("tactical"),
                    feedback.get("resource"),
                    feedback.get("rules"),
                    feedback.get("overall"),
                    tags_json,
                    feedback.get("note"),
                    now,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def record_move_feedback(self, *, game_id: str, sentiment: str, turn: int | None = None,
                             move_seq: int | None = None, move_desc: str | None = None,
                             reviewer: str | None = None) -> int:
        """Persist one per-move sentiment (like/neutral/dislike). Returns row id."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO move_feedback
                  (game_id, turn, move_seq, sentiment, move_desc, reviewer, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (game_id, turn, move_seq, sentiment, move_desc, reviewer, now),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def eval_report(self) -> dict:
        """Return an aggregate reliability + human-feedback scorecard across games."""
        with self._connect() as conn:
            dm = conn.execute(
                "SELECT COUNT(*) AS n, "
                "COALESCE(SUM(model_calls),0) AS calls, "
                "COALESCE(AVG(latency_ms),0) AS avg_lat, "
                "COALESCE(SUM(parse_retries),0) AS parse_r, "
                "COALESCE(SUM(legality_retries),0) AS legal_r, "
                "COALESCE(SUM(fell_back_to_pass),0) AS fallbacks, "
                "COALESCE(SUM(prompt_tokens),0) AS prompt_t, "
                "COALESCE(SUM(completion_tokens),0) AS completion_t, "
                "COALESCE(SUM(total_tokens),0) AS total_t, "
                "COALESCE(SUM(planner_model_calls),0) AS planner_calls, "
                "COALESCE(SUM(planner_total_tokens),0) AS planner_total_t, "
                "COALESCE(SUM(planner_prompt_tokens),0) AS planner_prompt_t, "
                "COALESCE(SUM(planner_completion_tokens),0) AS planner_completion_t, "
                "COALESCE(SUM(actor_model_calls),0) AS actor_calls, "
                "COALESCE(SUM(actor_total_tokens),0) AS actor_total_t, "
                "COALESCE(SUM(actor_prompt_tokens),0) AS actor_prompt_t, "
                "COALESCE(SUM(actor_completion_tokens),0) AS actor_completion_t "
                "FROM decision_eval_metrics"
            ).fetchone()
            cm = conn.execute(
                "SELECT COUNT(*) AS n, "
                "COALESCE(AVG(latency_ms),0) AS avg_lat, "
                "COALESCE(SUM(rejection_retries),0) AS rej, "
                "COALESCE(SUM(heuristic_fallback),0) AS heur, "
                "COALESCE(SUM(CASE WHEN accepted=1 THEN 1 ELSE 0 END),0) AS accepted, "
                "COALESCE(SUM(CASE WHEN accepted IS NOT NULL THEN 1 ELSE 0 END),0) AS resolved "
                "FROM client_decision_metrics"
            ).fetchone()
            latencies = [r["latency_ms"] for r in conn.execute(
                "SELECT latency_ms FROM decision_eval_metrics"
            ).fetchall()]
            hf = conn.execute(
                "SELECT COUNT(*) AS n, AVG(strategic) AS strategic, "
                "AVG(tactical) AS tactical, AVG(resource) AS resource, "
                "AVG(rules) AS rules, AVG(overall) AS overall FROM human_feedback"
            ).fetchone()
            mf = conn.execute(
                "SELECT COUNT(*) AS n, "
                "COALESCE(SUM(CASE WHEN sentiment='like' THEN 1 ELSE 0 END),0) AS likes, "
                "COALESCE(SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END),0) AS neutrals, "
                "COALESCE(SUM(CASE WHEN sentiment='dislike' THEN 1 ELSE 0 END),0) AS dislikes "
                "FROM move_feedback"
            ).fetchone()

        server_decisions = dm["n"]
        resolved = cm["resolved"]
        return {
            "server_side": {
                "decisions": server_decisions,
                "model_calls": dm["calls"],
                "avg_model_calls": round(dm["calls"] / server_decisions, 2) if server_decisions else 0,
                "avg_latency_ms": round(dm["avg_lat"], 1),
                "p95_latency_ms": _percentile(sorted(latencies), 95) if latencies else 0,
                "parse_retries": dm["parse_r"],
                "legality_retries": dm["legal_r"],
                "fallback_passes": dm["fallbacks"],
                "tokens": {
                    "prompt": dm["prompt_t"],
                    "completion": dm["completion_t"],
                    "total": dm["total_t"],
                    "avg_total_per_decision": round(dm["total_t"] / server_decisions, 1) if server_decisions else 0,
                    "planner": {
                        "model_calls": dm["planner_calls"],
                        "prompt": dm["planner_prompt_t"],
                        "completion": dm["planner_completion_t"],
                        "total": dm["planner_total_t"],
                    },
                    "actor": {
                        "model_calls": dm["actor_calls"],
                        "prompt": dm["actor_prompt_t"],
                        "completion": dm["actor_completion_t"],
                        "total": dm["actor_total_t"],
                    },
                },
            },
            "engine_observed": {
                "decisions": cm["n"],
                "avg_latency_ms": round(cm["avg_lat"], 1),
                "rejection_retries": cm["rej"],
                "heuristic_fallbacks": cm["heur"],
                "acceptance_rate": round(cm["accepted"] / resolved, 3) if resolved else None,
            },
            "human_feedback": {
                "submissions": hf["n"],
                "avg_strategic": round(hf["strategic"], 2) if hf["strategic"] is not None else None,
                "avg_tactical": round(hf["tactical"], 2) if hf["tactical"] is not None else None,
                "avg_resource": round(hf["resource"], 2) if hf["resource"] is not None else None,
                "avg_rules": round(hf["rules"], 2) if hf["rules"] is not None else None,
                "avg_overall": round(hf["overall"], 2) if hf["overall"] is not None else None,
            },
            "move_feedback": {
                "submissions": mf["n"],
                "likes": mf["likes"],
                "neutrals": mf["neutrals"],
                "dislikes": mf["dislikes"],
                "like_rate": round(mf["likes"] / mf["n"], 3) if mf["n"] else None,
            },
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _next_decision_index(self, game_id: str) -> int:
        idx = self._decision_counters.get(game_id, 0)
        self._decision_counters[game_id] = idx + 1
        return idx


def _hash_dict(d: dict) -> str:
    serialised = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


def _percentile(sorted_values: list[int], pct: int) -> int:
    """Nearest-rank percentile of an already-sorted list. Returns 0 when empty."""
    if not sorted_values:
        return 0
    k = max(0, min(len(sorted_values) - 1, int(round((pct / 100.0) * len(sorted_values) + 0.5)) - 1))
    return int(sorted_values[k])


def _params_summary(move: dict) -> str:
    p = move.get("parameters", {})
    if not p:
        return ""
    items = []
    for k, v in p.items():
        if isinstance(v, list):
            items.append(f"{k}=[{','.join(str(x) for x in v[:2])}]")
        elif v not in (None, "", False):
            items.append(f"{k}={v}")
    return ", ".join(items[:3])


# ── Decision file logger ──────────────────────────────────────────────────────


LOG_FILE = DEFAULT_DB_PATH.parent / "agent_decisions.log"

# Decision-type display labels (no colour — plain text file)
_DT_LABELS = {
    "mulligan":          "Mulligan",
    "main_phase":        "Main Phase",
    "showdown_focus":    "Showdown",
    "chain_reaction":    "Chain Reaction",
    "combat_assignment": "Combat Damage",
    "pending_choice":    "Pending Choice",
}

_DIVIDER = "─" * 72


def _wrap_text(text: str, width: int = 68, indent: str = "    ") -> str:
    words = text.split()
    lines: list[str] = []
    current = indent
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current.rstrip())
            current = indent + word + " "
        else:
            current += word + " "
    if current.strip():
        lines.append(current.rstrip())
    return "\n".join(lines)


def _format_params(params: dict) -> str:
    parts = []
    for k, v in params.items():
        if isinstance(v, list):
            parts.append(f"{k}=[{', '.join(str(x) for x in v)}]")
        elif v not in (None, "", False):
            parts.append(f"{k}={v}")
    return ("  " + "  ".join(parts)) if parts else ""


def format_decision_block(
    *,
    game_id: str,
    turn: int,
    decision_index: int,
    decision_type: str,
    timestamp: str,
    reasoning: str,
    action: str,
    parameters: dict,
    command: str,
    confidence: Optional[str] = None,
    alternatives_considered: Optional[str] = None,
) -> str:
    """Return a formatted plain-text block for one decision."""
    type_label = _DT_LABELS.get(decision_type, decision_type)
    conf_tag = f"  [{confidence}]" if confidence else ""
    params_str = _format_params(parameters)

    lines = [
        _DIVIDER,
        f"Turn {turn}  #{decision_index}  {type_label}{conf_tag}  {timestamp}",
        f"  Action:    {action}{params_str}",
        f"  Command:   {command}",
        f"  Game:      {game_id}",
        "  Reasoning:",
        _wrap_text(reasoning),
    ]
    if alternatives_considered:
        lines.append("  Alternatives:")
        lines.append(_wrap_text(alternatives_considered))
    return "\n".join(lines)


class DecisionLogger:
    """
    Appends one formatted plain-text block per decision to agent_decisions.log.

    The file is cleared automatically each time the server starts (call clear()
    in the lifespan handler).  Open it in any text editor or tail it live:

        tail -f ai_agent/agent_decisions.log
    """

    def __init__(self, log_path: Path = LOG_FILE) -> None:
        self._log_path = log_path

    def clear(self) -> None:
        """Truncate the log file.  Call once at server startup."""
        self._log_path.write_text(
            f"Riftbound AI Agent — Decision Log\n"
            f"Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"{'═' * 72}\n\n",
            encoding="utf-8",
        )

    def log(
        self,
        *,
        game_id: str,
        turn: int,
        decision_index: int,
        decision_type: str,
        reasoning: str,
        move: dict,
        command: str,
        confidence: Optional[str] = None,
        alternatives_considered: Optional[str] = None,
    ) -> None:
        block = format_decision_block(
            game_id=game_id,
            turn=turn,
            decision_index=decision_index,
            decision_type=decision_type,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            reasoning=reasoning,
            action=move.get("action", ""),
            parameters=move.get("parameters", {}),
            command=command,
            confidence=confidence,
            alternatives_considered=alternatives_considered,
        )
        with self._log_path.open("a", encoding="utf-8") as fh:
            fh.write(block + "\n\n")

    def close_all(self) -> None:
        pass  # no persistent handles needed


def _safe_filename(game_id: str) -> str:
    """Convert a game_id to a safe filename fragment."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in game_id)
    return safe[:60]
