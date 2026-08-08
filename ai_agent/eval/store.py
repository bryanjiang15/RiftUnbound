"""Isolated SQLite persistence for evaluation runs.

Never writes into live ``agent_memory.db``. Results live in a dedicated
``results.db`` under the run output directory.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .schemas import LayerResult, TrialResult

_DDL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    run_id TEXT PRIMARY KEY,
    description TEXT,
    mode TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    git_sha TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS eval_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    config_id TEXT NOT NULL,
    config_json TEXT NOT NULL,
    UNIQUE(run_id, config_id)
);

CREATE TABLE IF NOT EXISTS eval_case_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_json TEXT NOT NULL,
    UNIQUE(run_id, case_id)
);

CREATE TABLE IF NOT EXISTS eval_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    repetition INTEGER NOT NULL DEFAULT 0,
    transform TEXT NOT NULL DEFAULT 'identity',
    game_id TEXT,
    decision_json TEXT,
    reasoner_emit_json TEXT,
    tool_trace_json TEXT,
    metrics_json TEXT,
    overall_pass INTEGER NOT NULL DEFAULT 0,
    overall_score REAL,
    error TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run
    ON eval_results (run_id, profile_id, case_id);

CREATE TABLE IF NOT EXISTS eval_grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL,
    layer TEXT NOT NULL,
    passed INTEGER NOT NULL,
    score REAL,
    details_json TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    FOREIGN KEY(result_id) REFERENCES eval_results(id)
);

CREATE TABLE IF NOT EXISTS arena_games (
    game_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    pair_id TEXT NOT NULL,
    pair_leg TEXT NOT NULL,
    seed INTEGER NOT NULL,
    opponent_id TEXT NOT NULL,
    candidate_seat INTEGER NOT NULL,
    first_player_index INTEGER NOT NULL,
    winner_index INTEGER,
    candidate_won INTEGER,
    candidate_score INTEGER,
    opponent_score INTEGER,
    turns INTEGER,
    finished INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS arena_pairs (
    pair_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    seed INTEGER NOT NULL,
    opponent_id TEXT NOT NULL,
    candidate_wins INTEGER NOT NULL,
    pair_score INTEGER NOT NULL,
    both_finished INTEGER NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvalStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_DDL)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def start_run(
        self,
        *,
        run_id: str,
        description: str,
        mode: str,
        manifest: dict[str, Any],
        git_sha: str = "",
    ) -> None:
        with self._connect() as conn:
            # Re-running the same run_id replaces prior rows so summaries stay honest.
            grade_ids = conn.execute(
                "SELECT id FROM eval_results WHERE run_id=?", (run_id,)
            ).fetchall()
            for row in grade_ids:
                conn.execute("DELETE FROM eval_grades WHERE result_id=?", (row["id"],))
            conn.execute("DELETE FROM eval_results WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM eval_configs WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM eval_case_snapshots WHERE run_id=?", (run_id,))
            conn.execute(
                "INSERT OR REPLACE INTO eval_runs "
                "(run_id, description, mode, manifest_json, git_sha, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    run_id,
                    description,
                    mode,
                    json.dumps(manifest, default=str),
                    git_sha,
                    _now(),
                ),
            )

    def finish_run(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE eval_runs SET finished_at=? WHERE run_id=?",
                (_now(), run_id),
            )

    def record_config(self, run_id: str, config_id: str, config: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO eval_configs (run_id, config_id, config_json) "
                "VALUES (?, ?, ?)",
                (run_id, config_id, json.dumps(config, default=str)),
            )

    def record_case_snapshot(self, run_id: str, case_id: str, case: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO eval_case_snapshots (run_id, case_id, case_json) "
                "VALUES (?, ?, ?)",
                (run_id, case_id, json.dumps(case, default=str)),
            )

    def record_trial(self, run_id: str, trial: TrialResult) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO eval_results ("
                "run_id, case_id, profile_id, repetition, transform, game_id, "
                "decision_json, reasoner_emit_json, tool_trace_json, metrics_json, "
                "overall_pass, overall_score, error, timestamp"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    trial.case_id,
                    trial.profile_id,
                    trial.repetition,
                    trial.transform,
                    trial.game_id,
                    json.dumps(trial.decision, default=str),
                    json.dumps(trial.reasoner_emit, default=str),
                    json.dumps(trial.tool_trace, default=str),
                    json.dumps(trial.metrics, default=str),
                    1 if trial.overall_pass else 0,
                    trial.overall_score,
                    trial.error,
                    _now(),
                ),
            )
            result_id = int(cur.lastrowid)
            for layer in trial.layers:
                self._insert_grade(conn, result_id, layer)
            return result_id

    def _insert_grade(
        self, conn: sqlite3.Connection, result_id: int, layer: LayerResult
    ) -> None:
        conn.execute(
            "INSERT INTO eval_grades "
            "(result_id, layer, passed, score, details_json, severity) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                result_id,
                layer.layer,
                1 if layer.passed else 0,
                layer.score,
                json.dumps(layer.details, default=str),
                layer.severity,
            ),
        )

    def record_arena_game(self, run_id: str, game: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO arena_games ("
                "game_id, run_id, pair_id, pair_leg, seed, opponent_id, "
                "candidate_seat, first_player_index, winner_index, candidate_won, "
                "candidate_score, opponent_score, turns, finished, result_json, timestamp"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    game["game_id"],
                    run_id,
                    game["pair_id"],
                    game["pair_leg"],
                    int(game["seed"]),
                    game["opponent_id"],
                    int(game["candidate_seat"]),
                    int(game["first_player_index"]),
                    game.get("winner_index"),
                    game.get("candidate_won"),
                    game.get("candidate_score"),
                    game.get("opponent_score"),
                    game.get("turns"),
                    1 if game.get("finished") else 0,
                    json.dumps(game, default=str),
                    _now(),
                ),
            )

    def record_arena_pair(self, run_id: str, pair: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO arena_pairs ("
                "pair_id, run_id, seed, opponent_id, candidate_wins, pair_score, both_finished"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    pair["pair_id"],
                    run_id,
                    int(pair["seed"]),
                    pair["opponent_id"],
                    int(pair["candidate_wins"]),
                    int(pair["pair_score"]),
                    1 if pair.get("both_finished") else 0,
                ),
            )

    def list_trials(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_results WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_grades(self, result_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_grades WHERE result_id=? ORDER BY id",
                (result_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def summary(self, run_id: str) -> dict[str, Any]:
        trials = self.list_trials(run_id)
        by_profile: dict[str, dict[str, Any]] = {}
        for trial in trials:
            pid = trial["profile_id"]
            bucket = by_profile.setdefault(
                pid, {"n": 0, "passed": 0, "errors": 0, "scores": []}
            )
            bucket["n"] += 1
            if trial["overall_pass"]:
                bucket["passed"] += 1
            if trial.get("error"):
                bucket["errors"] += 1
            if trial.get("overall_score") is not None:
                bucket["scores"].append(float(trial["overall_score"]))
        return {"run_id": run_id, "trials": len(trials), "by_profile": by_profile}
