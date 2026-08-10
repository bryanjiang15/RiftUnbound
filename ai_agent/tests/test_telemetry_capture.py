"""Tests for GoalSet / Reasoner / turn_snapshot SQL telemetry capture."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ai_agent import capture as capture_mod
from ai_agent import goal_compiler as gc
from ai_agent.import_selfplay_logs import import_log
from ai_agent.memory import Memory
from ai_agent.schemas import (
    CandidateLine,
    Decision,
    DecisionRequest,
    Goal,
    GoalSet,
    Move,
    BriefState,
)


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
        "my_base_units": [
            {
                "instance_id": "u1",
                "name": "U",
                "current_might": 3,
                "base_might": 3,
                "location": "base",
                "is_exhausted": False,
                "is_stunned": False,
                "damage": 0,
                "buff_counters": 0,
                "keywords": [],
            }
        ],
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
    return Memory(db_path=tmp_path / "telemetry.db")


def test_goal_achievement_state_target_met():
    goal_set = GoalSet(
        turn=3,
        rationale="r",
        goals=[
            Goal(
                id="runes",
                kind="state_target",
                metric="my_ready_runes",
                comparator=">=",
                threshold=2,
                priority="med",
            )
        ],
    )
    overlay = gc.compile_goals(goal_set)
    delta, achieved = gc.goal_achievement_for_line(
        goal_set,
        overlay,
        features={"my_ready_runes": 2},
        score_breakdown={},
        moves=["pass"],
    )
    assert achieved["runes"]["met"] is True
    assert achieved["runes"]["satisfaction"] == pytest.approx(1.0)
    assert delta == pytest.approx(achieved["runes"]["delta"])


def test_capture_search_decision_persists_goal_fields(mem: Memory, monkeypatch):
    monkeypatch.setattr(gc, "weight_bias_features", lambda path=None: {
        "battlefield_control": "state_weights",
    })
    goal_set = GoalSet(
        turn=3,
        rationale="hold",
        goals=[
            Goal(
                id="runes",
                kind="state_target",
                metric="my_ready_runes",
                comparator=">=",
                threshold=1,
                priority="high",
            )
        ],
    )
    overlay = gc.compile_goals(goal_set)
    line = CandidateLine(
        line_id="L1",
        score=10.0,
        moves=["pass"],
        features={"my_ready_runes": 1},
        score_breakdown={"battlefield_control": 2.0},
    )
    request = DecisionRequest(
        brief_state=BriefState.model_validate(_brief()),
        game_id="g1",
        candidate_lines=[line],
    )
    decision = Decision(
        reasoning="ok",
        move=Move(action="pass"),
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
        goals_source="strategist",
        goal_set=goal_set,
        overlay=overlay,
    )
    with mem._connect() as conn:
        row = conn.execute("SELECT * FROM search_decisions").fetchone()
    assert row["goals_source"] == "strategist"
    assert row["goal_set_json"] is not None
    assert row["overlay_json"] is not None
    assert row["chosen_overlay_delta"] is not None
    achieved = json.loads(row["chosen_goal_achieved_json"])
    assert achieved["runes"]["met"] is True


def test_search_decisions_goal_columns_migrate(tmp_path: Path):
    db = tmp_path / "old.db"
    with sqlite3.connect(str(db)) as conn:
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
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(search_decisions)")}
    assert "goals_source" in cols
    assert "chosen_goal_achieved_json" in cols
    assert "goal_set_json" in cols


def test_capture_reasoner_decision_row(mem: Memory):
    telemetry = {
        "terminal_kind": "line",
        "investigation_satisfied": True,
        "novel_investigation": True,
        "local_fork_attempted": True,
        "novel_suffix_found": False,
        "comparison_required": True,
        "scout_agreement": False,
        "score_primary_rationale": False,
        "failed_search_calls": 1,
        "recovered_failed_searches": 1,
        "unique_sequence_count": 3,
        "max_complete_line_length": 2,
        "tool_mix": ["search_for", "deepen"],
        "selected_source_lineage": ["scout", "deepen"],
        "budget": {"nodes_used": 10, "budget_exhausted": False},
        "reasoner_latency_ms": 120,
        "engine_latency_ms": 40,
        "fallback_reason": "",
        "cache_hit": False,
        "tool_trace": [
            {
                "round": 0,
                "name": "search_for",
                "args": {"constraints": {"my_score": {"gte": 8}}},
                "result_status": "novel",
                "summary": "ok",
            }
        ],
    }
    capture_mod.capture_reasoner_decision(
        memory=mem,
        game_id="g1",
        turn=4,
        decision_index=2,
        root_state_hash="abc",
        telemetry=telemetry,
        chosen_line_id="L9",
        committed_line={"line_id": "L9", "complete": True, "moves": ["pass"]},
        rationale="Compared alternative.",
        eval_metrics={"model_calls": 2, "prompt_tokens": 100, "completion_tokens": 20},
    )
    with mem._connect() as conn:
        row = conn.execute("SELECT * FROM reasoner_decisions").fetchone()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "reasoner_decisions" in tables
    assert row["terminal_kind"] == "line"
    assert row["committed"] == 1
    assert row["chosen_line_complete"] == 1
    assert row["novel_investigation"] == 1
    assert json.loads(row["tool_mix_json"]) == ["search_for", "deepen"]
    assert row["model_calls"] == 2
    assert row["rationale_short"].startswith("Compared")


def test_compact_tool_trace_truncates_without_full_bodies():
    compact = capture_mod.compact_tool_trace(
        [
            {
                "round": 1,
                "name": "simulate_line",
                "args": {"moves": ["a" * 200]},
                "summary": "x" * 500,
                "result_status": "ok",
                "huge_result": {"nodes": list(range(1000))},
            }
        ]
    )
    assert compact[0]["name"] == "simulate_line"
    assert len(compact[0]["args"]["moves"]) <= 80
    assert len(compact[0]["summary"]) <= 200
    assert "huge_result" not in compact[0]


def test_turn_snapshot_capture_and_import(tmp_path: Path, mem: Memory):
    brief = _brief(turn_number=5)
    capture_mod.capture_turn_snapshot(
        memory=mem,
        game_id="g1",
        turn=5,
        brief_state=brief,
        my_player_index=0,
        turn_player_index=0,
    )
    with mem._connect() as conn:
        row = conn.execute("SELECT * FROM turn_snapshots").fetchone()
    assert row["turn"] == 5
    assert row["my_rune_count"] == 2
    assert row["my_ready_rune_count"] == 1
    assert row["cards_in_hand"] == 1
    assert row["bf_control_net"] == 1

    log_path = tmp_path / "cap.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "kind": "turn_snapshot",
                "game_id": "g2",
                "turn": 7,
                "brief_state": _brief(turn_number=7, my_score=4),
                "my_player_index": 1,
                "turn_player_index": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = import_log(
        log_path,
        db_path=tmp_path / "import.db",
        data_origin="self_play",
        capture_seat=None,
    )
    assert result["records"].get("turn_snapshot") == 1
    assert result["errors"] == 0
    imported = Memory(db_path=tmp_path / "import.db")
    with imported._connect() as conn:
        row = conn.execute(
            "SELECT turn, my_player_index, my_score FROM turn_snapshots"
        ).fetchone()
    assert row["turn"] == 7
    assert row["my_player_index"] == 1
    assert row["my_score"] == 4


def test_snapshot_scalars_include_rune_counts():
    scalars = capture_mod.snapshot_scalars(_brief())
    assert scalars["my_rune_count"] == 2
    assert scalars["my_ready_rune_count"] == 1
