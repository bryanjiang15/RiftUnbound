"""Capture + schema tests for authoritative analysis state and canonical outcomes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_agent import capture as capture_mod
from ai_agent.memory import Memory
from ai_agent.schemas import BriefState, CandidateLine, Decision, DecisionRequest, Move


def _brief(**overrides) -> dict:
    base = {
        "schema_version": "1.0",
        "game_id": "g1",
        "turn_number": 3,
        "my_player_index": 0,
        "turn_player_index": 0,
        "current_phase": "Main Phase",
        "current_state": "Neutral Open",
        "decision_type": "main_phase",
        "my_score": 2,
        "my_energy": 1,
        "my_power": {},
        "my_runes": [
            {"rune_index": 0, "domain": "fury", "is_exhausted": False},
            {"rune_index": 1, "domain": "fury", "is_exhausted": True},
        ],
        "my_hand": [
            {
                "instance_id": "c1",
                "name": "X",
                "card_type": "unit",
                "energy_cost": 1,
                "power_cost": [],
            }
        ],
        "my_base_units": [],
        "opponent_score": 1,
        "opponent_hand_size": 4,
        "opponent_base_units": [],
        "battlefields": [
            {
                "battlefield_id": "battlefield-a",
                "display_name": "A",
                "controller_index": 0,
                "my_units": [],
                "opponent_units": [],
                "is_contested": False,
                "has_facedown": False,
            }
        ],
        "legal_moves": ["pass", "end turn"],
    }
    base.update(overrides)
    return base


@pytest.fixture
def mem(tmp_path: Path) -> Memory:
    return Memory(db_path=tmp_path / "analysis.db")


def test_decision_request_accepts_analysis_state_without_prompt_fields():
    req = DecisionRequest(
        brief_state=BriefState.model_validate(_brief()),
        game_id="g1",
        analysis_state_json={"schema_version": "1", "replay": {"supported": True}, "cards": {}},
        analysis_state_schema_version="1",
        root_state_hash="abc123",
        candidate_lines=[CandidateLine(line_id="L1", score=1.0, moves=["pass"], search_state={"units": {}})],
    )
    dumped = req.model_dump()
    assert dumped["analysis_state_schema_version"] == "1"
    assert dumped["root_state_hash"] == "abc123"
    assert dumped["candidate_lines"][0]["search_state"] == {"units": {}}


def test_capture_persists_analysis_state_search_state_and_canonical_outcome(mem: Memory):
    analysis = {
        "schema_version": "1",
        "replay": {"supported": True, "reason": ""},
        "cards": {},
        "players": [],
    }
    line = CandidateLine(
        line_id="L1",
        score=12.0,
        moves=["play vi-destructive to battlefield-a", "end turn"],
        search_state={"players": {"me": {"score": 2}}, "units": {}},
        resolved_state={"my_score_after": 2},
    )
    request = DecisionRequest(
        brief_state=BriefState.model_validate(_brief()),
        game_id="g1",
        candidate_lines=[line],
        analysis_state_json=analysis,
        analysis_state_schema_version="1",
        root_state_hash="hash-root",
    )
    decision = Decision(
        reasoning="ok",
        move=Move(action="play_card", parameters={"card_id": "vi-destructive"}),
        chosen_line_id="L1",
        selector_source="argmax",
    )
    capture_mod.capture_search_decision(
        memory=mem,
        game_id="g1",
        decision_index=0,
        brief_state=_brief(),
        request=request,
        decision=decision,
        origin="self_play",
        weight_resolver=lambda _p: None,
    )
    capture_mod.capture_game_over(
        memory=mem,
        game_id="g1",
        winner_index=0,
        my_player_index=1,
        my_score=2,
        opp_score=8,
        total_turns=6,
        first_player_index=0,
        seed="s1",
    )
    with mem._connect() as conn:
        snap = conn.execute("SELECT * FROM decision_snapshots").fetchone()
        cand = conn.execute("SELECT * FROM candidate_lines").fetchone()
        game = conn.execute("SELECT * FROM games").fetchone()
    assert snap["root_state_hash"] == "hash-root"
    assert snap["analysis_state_schema_version"] == "1"
    stored = json.loads(snap["analysis_state_json"])
    assert stored["schema_version"] == "1"
    assert json.loads(cand["search_state_json"])["players"]["me"]["score"] == 2
    assert game["winner_index"] == 0
    assert game["p0_score"] == 8
    assert game["p1_score"] == 2
    # Seat-relative outcome still written (last reporter) but WPA uses winner_index.
    assert game["outcome"] == "loss"


def test_legacy_snapshot_without_analysis_state_is_detectable(mem: Memory):
    mem.record_decision_snapshot(
        game_id="legacy",
        turn=1,
        decision_index=0,
        scalars=capture_mod.snapshot_scalars(_brief()),
        brief_state=_brief(),
    )
    with mem._connect() as conn:
        row = conn.execute("SELECT analysis_state_json, root_state_hash FROM decision_snapshots").fetchone()
    assert row["analysis_state_json"] is None
    assert row["root_state_hash"] is None


def test_analysis_state_not_referenced_in_prompt_modules():
    """Capture-only: hidden analysis state must not leak into model prompts."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for rel in ("agent.py", "system_prompt.py", "reasoner.py", "strategist.py", "skills.py"):
        text = (root / rel).read_text(encoding="utf-8")
        if "analysis_state" in text:
            offenders.append(rel)
    assert offenders == []


def test_games_and_snapshot_columns_migrate(tmp_path: Path):
    db = tmp_path / "old.db"
    with __import__("sqlite3").connect(str(db)) as conn:
        conn.execute(
            """
            CREATE TABLE games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT UNIQUE NOT NULL,
                outcome TEXT,
                my_score INTEGER,
                opp_score INTEGER,
                turns_played INTEGER,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                decision_index INTEGER NOT NULL,
                brief_state_json TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE candidate_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_decision_id INTEGER NOT NULL,
                line_id TEXT,
                rank INTEGER,
                score REAL,
                chosen INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE search_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                decision_index INTEGER NOT NULL,
                num_candidates INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE decision_eval_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id TEXT NOT NULL,
                turn INTEGER NOT NULL,
                decision_index INTEGER NOT NULL,
                decision_type TEXT,
                model_calls INTEGER NOT NULL DEFAULT 0,
                retries INTEGER NOT NULL DEFAULT 0,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE game_eval_summary (
                game_id TEXT PRIMARY KEY,
                decisions_total INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL
            )
            """
        )
    mem = Memory(db_path=db)
    with mem._connect() as conn:
        game_cols = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
        snap_cols = {r["name"] for r in conn.execute("PRAGMA table_info(decision_snapshots)")}
        cand_cols = {r["name"] for r in conn.execute("PRAGMA table_info(candidate_lines)")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "winner_index" in game_cols
    assert "p0_score" in game_cols and "p1_score" in game_cols
    assert "analysis_state_json" in snap_cols
    assert "root_state_hash" in snap_cols
    assert "search_state_json" in cand_cols
    assert "counterfactual_runs" in tables
