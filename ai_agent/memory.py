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
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id            TEXT UNIQUE NOT NULL,
    outcome            TEXT,    -- 'win' | 'loss' | 'draw' | NULL = in progress
    my_score           INTEGER,
    opp_score          INTEGER,
    turns_played       INTEGER,
    first_player_index INTEGER, -- which seat took turn 1 (initiative bias control)
    seed               TEXT,    -- deck/shuffle seed (self-play reproducibility)
    timestamp          TEXT NOT NULL
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

-- ── Tuning dataset (storage doc §2) ─────────────────────────────────────────
-- One row per searched decision: the core Texel/CMA-ES training record.
CREATE TABLE IF NOT EXISTS search_decisions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id              TEXT    NOT NULL,
    turn                 INTEGER NOT NULL,
    decision_index       INTEGER NOT NULL,
    decision_type        TEXT,
    mode                 TEXT,        -- 'main' | 'reactive'
    my_player_index      INTEGER,     -- which seat made this decision (self-play)
    chosen_line_id       TEXT,
    chosen_line_score    REAL,
    best_candidate_score REAL,
    regret               REAL,        -- best − chosen
    score_margin         REAL,        -- best − 2nd-best
    num_candidates       INTEGER NOT NULL DEFAULT 0,
    chosen_breakdown_json TEXT,       -- per-term score_breakdown of chosen line
    chosen_features_json  TEXT,       -- raw build_score_features dict (Texel input)
    search_stats_json    TEXT,        -- nodes/branches/beam/elapsed/stopped_reason
    selector_source      TEXT,        -- 'llm' | 'fallback' | 'argmax'
    selector_reasoning   TEXT,
    origin               TEXT,        -- 'self_play' | 'vs_human' | 'vs_heuristic'
    -- GoalSet / overlay telemetry (may be null when goals off / argmax):
    goals_source         TEXT,        -- 'strategist' | 'reasoner' | 'none'
    goal_set_json        TEXT,
    overlay_json         TEXT,
    chosen_overlay_delta REAL,
    chosen_goal_achieved_json TEXT,   -- {goal_id: {satisfaction, met, delta}}
    -- backfilled at game end:
    went_first           INTEGER,     -- 1 = deciding seat took turn 1
    game_outcome         TEXT,        -- 'win' | 'loss' | 'draw'
    final_score_diff     INTEGER,
    weight_version_id    INTEGER,
    timestamp            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_dec_game ON search_decisions (game_id, turn, decision_index);

-- One row per candidate line per searched decision (search vs eval vs selection
-- error analysis; "was the realized-best line even generated?").
CREATE TABLE IF NOT EXISTS candidate_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    search_decision_id  INTEGER NOT NULL,
    line_id             TEXT,
    rank                INTEGER,
    score               REAL,
    chosen              INTEGER NOT NULL DEFAULT 0,
    moves_json          TEXT,
    breakdown_json      TEXT,
    features_json       TEXT,
    resolved_state_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_cand_lines_dec ON candidate_lines (search_decision_id);

-- Full queryable state at each searched decision (replaces hash-only). Compact
-- normalized BriefState JSON + extracted scalar columns for fast SQL filtering.
CREATE TABLE IF NOT EXISTS decision_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id           TEXT    NOT NULL,
    turn              INTEGER NOT NULL,
    decision_index    INTEGER NOT NULL,
    my_score          INTEGER,
    opp_score         INTEGER,
    my_energy         INTEGER,
    board_might_diff  INTEGER,
    cards_in_hand     INTEGER,
    cards_in_hand_opp INTEGER,
    bf_control_net    INTEGER,
    brief_state_json  TEXT,
    timestamp         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dec_snap_game ON decision_snapshots (game_id, turn, decision_index);

-- Every scoring profile that produced data, so results are attributable (A/B).
CREATE TABLE IF NOT EXISTS weight_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_hash TEXT UNIQUE NOT NULL,
    profile_json TEXT NOT NULL,
    git_sha      TEXT,
    created_at   TEXT NOT NULL
);

-- ── Per-card statistics (storage doc §3) ────────────────────────────────────
-- One row per card lifecycle event. The aggregation key is the BASE
-- definition_id (`card_def_id`), stamped directly from the allocator/instance —
-- never reverse-engineered from instance_id (see doc §3 join-key note).
CREATE TABLE IF NOT EXISTS card_events (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id              TEXT    NOT NULL,
    turn                 INTEGER NOT NULL,
    my_player_index      INTEGER,     -- reporting seat (self-play separation)
    card_def_id          TEXT    NOT NULL,  -- base definition_id (aggregation key)
    instance_id          TEXT,             -- per-copy id, e.g. 'garen-2'
    event                TEXT    NOT NULL,  -- drawn|played|discarded|died|
                                            -- mulliganed|scored|left_in_hand_at_end|
                                            -- in_opening_hand
    energy_spent         INTEGER NOT NULL DEFAULT 0,
    breakdown_delta_json TEXT,             -- optional score_breakdown contribution
    timestamp            TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_card_events_game ON card_events (game_id, turn);
CREATE INDEX IF NOT EXISTS idx_card_events_def ON card_events (card_def_id, event);

-- Compact Reasoner investigation summary (one row per /reason).
CREATE TABLE IF NOT EXISTS reasoner_decisions (
    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id                   TEXT    NOT NULL,
    turn                      INTEGER NOT NULL,
    decision_index            INTEGER,
    root_state_hash           TEXT,
    terminal_kind             TEXT,
    committed                 INTEGER,
    chosen_line_id            TEXT,
    chosen_line_complete      INTEGER,
    fallback_reason           TEXT,
    cache_hit                 INTEGER,
    investigation_satisfied   INTEGER,
    investigation_exemption   TEXT,
    novel_investigation       INTEGER,
    local_fork_attempted      INTEGER,
    novel_suffix_found        INTEGER,
    comparison_required       INTEGER,
    scout_agreement           INTEGER,
    score_primary_rationale   INTEGER,
    failed_search_calls       INTEGER,
    recovered_failed_searches INTEGER,
    unique_sequence_count     INTEGER,
    max_complete_line_length  INTEGER,
    tool_mix_json             TEXT,
    selected_source_lineage_json TEXT,
    budget_json               TEXT,
    reasoner_latency_ms       INTEGER,
    engine_latency_ms         INTEGER,
    model_calls               INTEGER,
    prompt_tokens             INTEGER,
    completion_tokens         INTEGER,
    rationale_short           TEXT,
    timestamp                 TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reasoner_dec_game ON reasoner_decisions (game_id, turn);

-- End-of-turn board pulse for WPA / swing-turn analysis.
CREATE TABLE IF NOT EXISTS turn_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id            TEXT    NOT NULL,
    turn               INTEGER NOT NULL,
    my_player_index    INTEGER,
    turn_player_index  INTEGER,
    my_score           INTEGER,
    opp_score          INTEGER,
    my_energy          INTEGER,
    board_might_diff   INTEGER,
    cards_in_hand      INTEGER,
    cards_in_hand_opp  INTEGER,
    bf_control_net     INTEGER,
    my_rune_count      INTEGER,
    my_ready_rune_count INTEGER,
    brief_state_json   TEXT,
    timestamp          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turn_snap_game ON turn_snapshots (game_id, turn, my_player_index);
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
            "search_decisions": [
                "goals_source TEXT",
                "goal_set_json TEXT",
                "overlay_json TEXT",
                "chosen_overlay_delta REAL",
                "chosen_goal_achieved_json TEXT",
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

    # ── Per-card statistics writes (storage doc §3) ─────────────────────────────

    _CARD_EVENTS = {
        "drawn", "played", "discarded", "died", "mulliganed", "scored",
        "left_in_hand_at_end", "in_opening_hand",
    }

    def record_card_event(
        self,
        *,
        game_id: str,
        turn: int,
        card_def_id: str,
        event: str,
        instance_id: Optional[str] = None,
        my_player_index: Optional[int] = None,
        energy_spent: int = 0,
        breakdown_delta: Optional[dict] = None,
    ) -> None:
        """Append one card lifecycle event. Called via /card_event.

        ``card_def_id`` is the BASE definition_id, stamped directly from the
        instance's definition (never derived from instance_id — see doc §3).
        """
        if event not in self._CARD_EVENTS:
            raise ValueError(f"unknown card event: {event!r}")
        now = datetime.now(timezone.utc).isoformat()
        breakdown_json = json.dumps(breakdown_delta) if breakdown_delta else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO card_events
                  (game_id, turn, my_player_index, card_def_id, instance_id,
                   event, energy_spent, breakdown_delta_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    my_player_index,
                    card_def_id,
                    instance_id,
                    event,
                    energy_spent,
                    breakdown_json,
                    now,
                ),
            )

    def record_game_outcome(
        self,
        *,
        game_id: str,
        outcome: str,
        my_score: int,
        opp_score: int,
        turns_played: int,
        first_player_index: Optional[int] = None,
        seed: Optional[str] = None,
    ) -> None:
        """Upsert a completed game record. Called via /game_over."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO games
                  (game_id, outcome, my_score, opp_score, turns_played,
                   first_player_index, seed, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    outcome=excluded.outcome,
                    my_score=excluded.my_score,
                    opp_score=excluded.opp_score,
                    turns_played=excluded.turns_played,
                    first_player_index=COALESCE(excluded.first_player_index, games.first_player_index),
                    seed=COALESCE(excluded.seed, games.seed),
                    timestamp=excluded.timestamp
                """,
                (
                    game_id,
                    outcome,
                    my_score,
                    opp_score,
                    turns_played,
                    first_player_index,
                    seed,
                    now,
                ),
            )

    # ── Tuning dataset writes (storage doc §2) ──────────────────────────────────

    def record_weight_version(
        self, *, profile_json: str, git_sha: Optional[str] = None
    ) -> int:
        """Upsert the scoring profile that is producing data; return its row id.

        Idempotent on profile content (profile_hash UNIQUE), so restarting the
        server with an unchanged profile reuses the same weight_version id.
        """
        profile_hash = hashlib.sha256(profile_json.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO weight_versions (profile_hash, profile_json, git_sha, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_hash) DO NOTHING
                """,
                (profile_hash, profile_json, git_sha, now),
            )
            row = conn.execute(
                "SELECT id FROM weight_versions WHERE profile_hash=?", (profile_hash,)
            ).fetchone()
            return int(row["id"]) if row else 0

    def record_search_decision(
        self,
        *,
        game_id: str,
        turn: int,
        decision_index: int,
        decision_type: Optional[str],
        mode: Optional[str],
        my_player_index: Optional[int],
        chosen_line_id: Optional[str],
        chosen_line_score: Optional[float],
        best_candidate_score: Optional[float],
        regret: Optional[float],
        score_margin: Optional[float],
        num_candidates: int,
        chosen_breakdown: Optional[dict],
        chosen_features: Optional[dict],
        search_stats: Optional[dict],
        selector_source: Optional[str],
        selector_reasoning: Optional[str],
        origin: Optional[str],
        weight_version_id: Optional[int],
        candidates: Optional[list[dict]] = None,
        goals_source: Optional[str] = None,
        goal_set: Optional[dict] = None,
        overlay: Optional[dict] = None,
        chosen_overlay_delta: Optional[float] = None,
        chosen_goal_achieved: Optional[dict] = None,
    ) -> int:
        """Persist one searched decision plus its candidate lines. Returns row id."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO search_decisions
                  (game_id, turn, decision_index, decision_type, mode,
                   my_player_index, chosen_line_id, chosen_line_score, best_candidate_score,
                   regret, score_margin, num_candidates,
                   chosen_breakdown_json, chosen_features_json, search_stats_json,
                   selector_source, selector_reasoning, origin,
                   goals_source, goal_set_json, overlay_json,
                   chosen_overlay_delta, chosen_goal_achieved_json,
                   weight_version_id, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    decision_index,
                    decision_type,
                    mode,
                    my_player_index,
                    chosen_line_id,
                    chosen_line_score,
                    best_candidate_score,
                    regret,
                    score_margin,
                    num_candidates,
                    json.dumps(chosen_breakdown) if chosen_breakdown is not None else None,
                    json.dumps(chosen_features) if chosen_features is not None else None,
                    json.dumps(search_stats) if search_stats is not None else None,
                    selector_source,
                    selector_reasoning,
                    origin,
                    goals_source,
                    json.dumps(goal_set) if goal_set is not None else None,
                    json.dumps(overlay) if overlay is not None else None,
                    chosen_overlay_delta,
                    json.dumps(chosen_goal_achieved) if chosen_goal_achieved is not None else None,
                    weight_version_id,
                    now,
                ),
            )
            decision_id = int(cur.lastrowid)  # type: ignore[arg-type]
            for cand in candidates or []:
                conn.execute(
                    """
                    INSERT INTO candidate_lines
                      (search_decision_id, line_id, rank, score, chosen,
                       moves_json, breakdown_json, features_json, resolved_state_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        cand.get("line_id"),
                        cand.get("rank"),
                        cand.get("score"),
                        1 if cand.get("chosen") else 0,
                        json.dumps(cand.get("moves")) if cand.get("moves") is not None else None,
                        json.dumps(cand.get("breakdown")) if cand.get("breakdown") is not None else None,
                        json.dumps(cand.get("features")) if cand.get("features") is not None else None,
                        json.dumps(cand.get("resolved_state")) if cand.get("resolved_state") is not None else None,
                    ),
                )
            return decision_id

    def record_decision_snapshot(
        self,
        *,
        game_id: str,
        turn: int,
        decision_index: int,
        scalars: dict,
        brief_state: dict,
    ) -> None:
        """Persist the full BriefState at a decision + extracted scalar columns."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decision_snapshots
                  (game_id, turn, decision_index, my_score, opp_score, my_energy,
                   board_might_diff, cards_in_hand, cards_in_hand_opp, bf_control_net,
                   brief_state_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    decision_index,
                    scalars.get("my_score"),
                    scalars.get("opp_score"),
                    scalars.get("my_energy"),
                    scalars.get("board_might_diff"),
                    scalars.get("cards_in_hand"),
                    scalars.get("cards_in_hand_opp"),
                    scalars.get("bf_control_net"),
                    json.dumps(brief_state),
                    now,
                ),
            )

    def record_reasoner_decision(
        self,
        *,
        game_id: str,
        turn: int,
        decision_index: Optional[int],
        root_state_hash: Optional[str],
        telemetry: dict,
        chosen_line_id: Optional[str] = None,
        committed: Optional[bool] = None,
        chosen_line_complete: Optional[bool] = None,
        rationale: Optional[str] = None,
        model_calls: Optional[int] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> int:
        """Persist one compact Reasoner investigation summary. Returns row id."""
        now = datetime.now(timezone.utc).isoformat()
        tel = telemetry or {}
        terminal_kind = tel.get("terminal_kind")
        if committed is None:
            committed = terminal_kind == "line"
        rationale_short = None
        if rationale:
            rationale_short = rationale if len(rationale) <= 200 else rationale[:197] + "..."
        elif tel.get("fallback_reason"):
            fr = str(tel.get("fallback_reason") or "")
            rationale_short = fr if len(fr) <= 200 else fr[:197] + "..."

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO reasoner_decisions
                  (game_id, turn, decision_index, root_state_hash, terminal_kind,
                   committed, chosen_line_id, chosen_line_complete, fallback_reason,
                   cache_hit, investigation_satisfied, investigation_exemption,
                   novel_investigation, local_fork_attempted, novel_suffix_found,
                   comparison_required, scout_agreement, score_primary_rationale,
                   failed_search_calls, recovered_failed_searches,
                   unique_sequence_count, max_complete_line_length,
                   tool_mix_json, selected_source_lineage_json, budget_json,
                   reasoner_latency_ms, engine_latency_ms,
                   model_calls, prompt_tokens, completion_tokens,
                   rationale_short, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    decision_index,
                    root_state_hash or tel.get("root_state_hash"),
                    terminal_kind,
                    None if committed is None else (1 if committed else 0),
                    chosen_line_id,
                    None if chosen_line_complete is None else (1 if chosen_line_complete else 0),
                    tel.get("fallback_reason") or None,
                    None if tel.get("cache_hit") is None else (1 if tel.get("cache_hit") else 0),
                    None if tel.get("investigation_satisfied") is None else (
                        1 if tel.get("investigation_satisfied") else 0
                    ),
                    tel.get("investigation_exemption"),
                    None if tel.get("novel_investigation") is None else (
                        1 if tel.get("novel_investigation") else 0
                    ),
                    None if tel.get("local_fork_attempted") is None else (
                        1 if tel.get("local_fork_attempted") else 0
                    ),
                    None if tel.get("novel_suffix_found") is None else (
                        1 if tel.get("novel_suffix_found") else 0
                    ),
                    None if tel.get("comparison_required") is None else (
                        1 if tel.get("comparison_required") else 0
                    ),
                    None if tel.get("scout_agreement") is None else (
                        1 if tel.get("scout_agreement") else 0
                    ),
                    None if tel.get("score_primary_rationale") is None else (
                        1 if tel.get("score_primary_rationale") else 0
                    ),
                    tel.get("failed_search_calls"),
                    tel.get("recovered_failed_searches"),
                    tel.get("unique_sequence_count", tel.get("registry_unique_sequences")),
                    tel.get("max_complete_line_length"),
                    json.dumps(tel.get("tool_mix")) if tel.get("tool_mix") is not None else None,
                    json.dumps(tel.get("selected_source_lineage"))
                    if tel.get("selected_source_lineage") is not None
                    else None,
                    json.dumps(tel.get("budget")) if tel.get("budget") is not None else None,
                    tel.get("reasoner_latency_ms"),
                    tel.get("engine_latency_ms"),
                    model_calls if model_calls is not None else tel.get("model_calls"),
                    prompt_tokens if prompt_tokens is not None else tel.get("prompt_tokens"),
                    completion_tokens
                    if completion_tokens is not None
                    else tel.get("completion_tokens"),
                    rationale_short,
                    now,
                ),
            )
            return int(cur.lastrowid)  # type: ignore[arg-type]

    def record_turn_snapshot(
        self,
        *,
        game_id: str,
        turn: int,
        my_player_index: Optional[int],
        turn_player_index: Optional[int],
        scalars: dict,
        brief_state: Optional[dict] = None,
    ) -> None:
        """Persist one end-of-turn board pulse for WPA / swing-turn analysis."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO turn_snapshots
                  (game_id, turn, my_player_index, turn_player_index,
                   my_score, opp_score, my_energy, board_might_diff,
                   cards_in_hand, cards_in_hand_opp, bf_control_net,
                   my_rune_count, my_ready_rune_count, brief_state_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game_id,
                    turn,
                    my_player_index,
                    turn_player_index,
                    scalars.get("my_score"),
                    scalars.get("opp_score"),
                    scalars.get("my_energy"),
                    scalars.get("board_might_diff"),
                    scalars.get("cards_in_hand"),
                    scalars.get("cards_in_hand_opp"),
                    scalars.get("bf_control_net"),
                    scalars.get("my_rune_count"),
                    scalars.get("my_ready_rune_count"),
                    json.dumps(brief_state) if brief_state is not None else None,
                    now,
                ),
            )

    def backfill_game_outcome(
        self,
        *,
        game_id: str,
        game_outcome: str,
        final_score_diff: int,
        my_player_index: int,
        first_player_index: Optional[int],
    ) -> None:
        """Label this game's search_decisions with the final result + initiative.

        The single most important wiring step: without it the tuner has no label
        on its feature vectors. `went_first` is 1 when the deciding seat (always the
        AI/my seat for captured rows) took turn 1.
        """
        went_first: Optional[int]
        if first_player_index is None:
            went_first = None
        else:
            went_first = 1 if first_player_index == my_player_index else 0
        with self._connect() as conn:
            # Seat-aware: only label rows this seat produced, so two-seat self-play
            # (shared game_id) doesn't cross-contaminate went_first / outcome.
            conn.execute(
                """
                UPDATE search_decisions
                SET game_outcome=?, final_score_diff=?, went_first=?
                WHERE game_id=? AND (my_player_index=? OR my_player_index IS NULL)
                """,
                (
                    game_outcome,
                    final_score_diff,
                    went_first,
                    game_id,
                    my_player_index,
                ),
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

    def card_stats_report(self, *, min_plays: int = 20) -> dict:
        """Per-card aggregate statistics (storage doc §3 derived view).

        Aggregation key is the base ``card_def_id``. WPA is intentionally
        omitted here — ``turn_snapshots`` are now captured, but this report does
        not yet compute Δ win-probability from them. Cards below ``min_plays``
        are returned in ``low_sample`` rather than ``cards`` so the sample-size
        caveat is explicit, not silently mixed in.
        """
        with self._connect() as conn:
            games_total = conn.execute(
                "SELECT COUNT(*) AS n FROM games"
            ).fetchone()["n"] or 0
            base_win_rate = None
            if games_total:
                wins = conn.execute(
                    "SELECT COUNT(*) AS n FROM games WHERE outcome='win'"
                ).fetchone()["n"] or 0
                base_win_rate = round(wins / games_total, 3)

            rows = conn.execute(
                """
                SELECT
                    card_def_id,
                    COUNT(DISTINCT CASE WHEN event IN ('drawn','in_opening_hand')
                          THEN game_id END)                                  AS games_seen,
                    COUNT(DISTINCT CASE WHEN event='played' THEN game_id END) AS games_played,
                    SUM(CASE WHEN event='drawn' THEN 1 ELSE 0 END)           AS drawn,
                    SUM(CASE WHEN event='in_opening_hand' THEN 1 ELSE 0 END) AS opening_hand,
                    SUM(CASE WHEN event='played' THEN 1 ELSE 0 END)          AS played,
                    SUM(CASE WHEN event='discarded' THEN 1 ELSE 0 END)       AS discarded,
                    SUM(CASE WHEN event='mulliganed' THEN 1 ELSE 0 END)      AS mulliganed,
                    SUM(CASE WHEN event='scored' THEN 1 ELSE 0 END)          AS scored,
                    SUM(CASE WHEN event='died' THEN 1 ELSE 0 END)            AS died,
                    SUM(CASE WHEN event='left_in_hand_at_end' THEN 1 ELSE 0 END) AS stuck,
                    AVG(CASE WHEN event='played' THEN turn END)             AS avg_turn_played,
                    AVG(CASE WHEN event='played' THEN energy_spent END)    AS avg_energy_spent
                FROM card_events
                GROUP BY card_def_id
                """
            ).fetchall()

            # Win-rate-when-played: distinct (card, game) played, joined to outcome.
            wr_rows = conn.execute(
                """
                SELECT ce.card_def_id AS card_def_id,
                       COUNT(*) AS played_games,
                       SUM(CASE WHEN g.outcome='win' THEN 1 ELSE 0 END) AS played_wins
                FROM (
                    SELECT DISTINCT card_def_id, game_id
                    FROM card_events WHERE event='played'
                ) ce
                JOIN games g ON g.game_id = ce.game_id
                WHERE g.outcome IS NOT NULL
                GROUP BY ce.card_def_id
                """
            ).fetchall()
            wr_by_card = {
                r["card_def_id"]: (r["played_games"], r["played_wins"])
                for r in wr_rows
            }

        cards: list[dict] = []
        low_sample: list[dict] = []
        for r in rows:
            drawn = r["drawn"] or 0
            played = r["played"] or 0
            played_games, played_wins = wr_by_card.get(r["card_def_id"], (0, 0))
            win_rate_when_played = (
                round(played_wins / played_games, 3) if played_games else None
            )
            stat = {
                "card_def_id": r["card_def_id"],
                "games_seen": r["games_seen"] or 0,
                "games_played": r["games_played"] or 0,
                # frequency / tempo
                "draw_rate": round((r["games_seen"] or 0) / games_total, 3) if games_total else None,
                "play_rate": round((r["games_played"] or 0) / games_total, 3) if games_total else None,
                "play_when_drawn_rate": round(played / drawn, 3) if drawn else None,
                "mulligan_rate": round((r["mulliganed"] or 0) / drawn, 3) if drawn else None,
                "stuck_in_hand_rate": round((r["stuck"] or 0) / drawn, 3) if drawn else None,
                "avg_turn_played": round(r["avg_turn_played"], 2) if r["avg_turn_played"] is not None else None,
                "avg_energy_spent": round(r["avg_energy_spent"], 2) if r["avg_energy_spent"] is not None else None,
                # raw counts
                "drawn": drawn,
                "played": played,
                "discarded": r["discarded"] or 0,
                "scored": r["scored"] or 0,
                "deaths": r["died"] or 0,
                # impact (survivorship-biased — see caveat)
                "win_rate_when_played": win_rate_when_played,
            }
            (cards if played >= min_plays else low_sample).append(stat)

        cards.sort(key=lambda c: c["played"], reverse=True)
        low_sample.sort(key=lambda c: c["played"], reverse=True)
        return {
            "games_total": games_total,
            "base_win_rate": base_win_rate,
            "min_plays": min_plays,
            "cards": cards,
            "low_sample": low_sample,
            "note": (
                "WPA not computed yet (turn_snapshots are captured; this report "
                "does not derive ΔWP). win_rate_when_played is survivorship-biased."
            ),
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
