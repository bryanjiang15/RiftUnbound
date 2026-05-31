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
"""

# Maximum number of recent events to inject into context
RECENT_SLICE_SIZE = 10


class Memory:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._decision_counters: dict[str, int] = {}
        self._init_db()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

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

    def opponent_slice(self, game_id: str, n: int = 8) -> str:
        """Return the last n opponent actions for this game as a formatted context string."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT turn, action FROM opponent_actions WHERE game_id=? ORDER BY id DESC LIMIT ?",
                (game_id, n),
            ).fetchall()
        if not rows:
            return ""
        lines = ["## Opponent actions (recent, oldest first)"]
        for row in reversed(rows):
            lines.append(f"  Turn {row['turn']}: {row['action']}")
        return "\n".join(lines)

    def recent_slice(self, game_id: str, n: int = RECENT_SLICE_SIZE) -> str:
        """Return the last n decisions for this game as a formatted context string."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT turn, decision_index, decision_type, reasoning,
                       move_json, accepted, rejection_reason, outcome_summary
                FROM decisions
                WHERE game_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (game_id, n),
            ).fetchall()

        if not rows:
            return ""

        lines: list[str] = ["## Recent game history (oldest first)"]
        for row in reversed(rows):
            move = json.loads(row["move_json"])
            accepted_str = {None: "?", 1: "OK", 0: "REJECTED"}.get(row["accepted"], "?")
            lines.append(
                f"  Turn {row['turn']} #{row['decision_index']} [{row['decision_type']}]: "
                f"{move.get('action', '?')}({_params_summary(move)}) → {accepted_str}"
            )
            if row["rejection_reason"]:
                lines.append(f"    Rejection: {row['rejection_reason']}")
            if row["outcome_summary"]:
                lines.append(f"    Outcome: {row['outcome_summary']}")
            if row["reasoning"]:
                lines.append(f"    Reasoning: {row['reasoning'][:200]}")
        return "\n".join(lines)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _next_decision_index(self, game_id: str) -> int:
        idx = self._decision_counters.get(game_id, 0)
        self._decision_counters[game_id] = idx + 1
        return idx


def _hash_dict(d: dict) -> str:
    serialised = json.dumps(d, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:16]


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
