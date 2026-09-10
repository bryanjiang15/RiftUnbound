from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from ai_agent import main
from ai_agent.schemas import Goal, GoalSet, ReasonRequest, ReasonerEmit


def _brief() -> dict:
    return {
        "game_id": "g",
        "turn_number": 2,
        "my_player_index": 0,
        "turn_player_index": 0,
        "current_phase": "Main Phase",
        "current_state": "Neutral Open",
        "decision_type": "main_phase",
        "my_score": 0,
        "my_energy": 0,
        "my_power": {},
        "my_runes": [],
        "my_hand": [],
        "my_base_units": [],
        "opponent_score": 0,
        "opponent_hand_size": 0,
        "opponent_base_units": [],
        "battlefields": [],
        "legal_moves": ["pass", "end turn"],
    }


def test_reason_endpoint_returns_full_canonical_committed_line(tmp_path):
    from ai_agent.memory import Memory

    committed = {
        "line_id": "deepen-1-line-1-abc",
        "moves": ["pass", "end turn"],
        "move_contexts": [{}, {}],
        "expected_pre_hashes": ["root", "next"],
        "root_state_hash": "root",
        "legal": True,
        "complete": True,
        "terminal_reason": "end_turn",
        "search_mode": "main",
        "score": 1.5,
    }
    emit = ReasonerEmit(
        kind="line",
        confidence="commit",
        chosen_line_id=committed["line_id"],
        rationale="Alternative compared with scout.",
    )
    analysis = {
        "schema_version": "1",
        "replay": {"supported": True, "reason": ""},
        "cards": {},
        "players": [],
        "board": {},
    }
    request = ReasonRequest(
        brief_state=_brief(),
        game_id="g",
        root_state_hash="root",
        analysis_state_json=analysis,
        analysis_state_schema_version="1",
        candidate_lines=[],
    )

    async def fake_run(**kwargs):
        return emit, committed, {
            "terminal_kind": "line",
            "tool_mix": ["search_for"],
            "tool_trace": [{"round": 0, "name": "search_for", "args": {}, "summary": "ok"}],
            "novel_investigation": True,
        }

    old_memory = main._memory
    old_enabled = main._reasoner_enabled
    old_search = main._search_enabled
    mem = Memory(db_path=tmp_path / "reason.db")
    main._memory = mem
    main._reasoner_enabled = True
    main._search_enabled = True
    try:
        with patch("ai_agent.main.run_reasoner", side_effect=fake_run):
            payload = asyncio.run(main.reason_endpoint(request))
    finally:
        main._memory = old_memory
        main._reasoner_enabled = old_enabled
        main._search_enabled = old_search
    assert payload["kind"] == "line"
    assert payload["committed_line"] == committed
    assert payload["root_state_hash"] == "root"
    with mem._connect() as conn:
        row = conn.execute("SELECT * FROM reasoner_decisions").fetchone()
        dec = conn.execute("SELECT * FROM decisions").fetchone()
        snap = conn.execute("SELECT * FROM decision_snapshots").fetchone()
        search = conn.execute("SELECT * FROM search_decisions").fetchone()
        cands = conn.execute("SELECT * FROM candidate_lines").fetchall()
    assert row is not None
    assert row["terminal_kind"] == "line"
    assert row["chosen_line_id"] == committed["line_id"]
    assert row["committed"] == 1
    assert row["decision_index"] == 0
    # Same capture shape as /decision so Analysis UI can list/step the commit.
    assert dec is not None
    assert dec["decision_type"] == "main_phase"
    assert dec["decision_index"] == 0
    move = json.loads(dec["move_json"])
    assert move["action"] == "pass"
    assert snap is not None
    assert snap["root_state_hash"] == "root"
    assert snap["analysis_state_json"] is not None
    analysis_stored = json.loads(snap["analysis_state_json"])
    assert analysis_stored["replay"]["supported"] is True
    assert search is not None
    assert search["chosen_line_id"] == committed["line_id"]
    assert search["selector_source"] == "reasoner"
    assert search["goals_source"] == "reasoner"
    assert any(c["line_id"] == committed["line_id"] and c["chosen"] == 1 for c in cands)


def test_reason_endpoint_missing_root_uses_explicit_base_search_fallback():
    request = ReasonRequest(brief_state=_brief(), game_id="g")
    old_memory = main._memory
    old_enabled = main._reasoner_enabled
    main._memory = object()
    main._reasoner_enabled = True
    try:
        payload = asyncio.run(main.reason_endpoint(request))
    finally:
        main._memory = old_memory
        main._reasoner_enabled = old_enabled
    assert payload["kind"] == "base_search_fallback"
    assert payload["committed_line"] is None
    assert payload["telemetry"]["fallback_reason"] == "missing_root_state_hash"


def test_reasoner_overlay_cache_is_scoped_by_decision_type():
    goal_set = GoalSet(
        turn=2,
        goals=[
            Goal(
                id="hold-a",
                kind="state_target",
                metric="bf_control_net",
                metric_key="battlefield-a",
                comparator="==",
                threshold=1,
            )
        ],
    )
    emit = ReasonerEmit(
        kind="goals",
        confidence="goals",
        goal_set=goal_set,
        rationale="Hold battlefield-a.",
    )
    request = ReasonRequest(
        brief_state=_brief(),
        game_id="g",
        root_state_hash="root",
    )

    async def fake_run(**kwargs):
        return emit, None, {"terminal_kind": "goals"}

    old_memory = main._memory
    old_enabled = main._reasoner_enabled
    old_overlays = dict(main._reasoner_overlays)
    main._memory = object()
    main._reasoner_enabled = True
    main._reasoner_overlays.clear()
    try:
        with patch("ai_agent.main.run_reasoner", side_effect=fake_run):
            asyncio.run(main.reason_endpoint(request))
        main_key = main._reasoner_overlay_key("g", _brief())
        reactive_key = main._reasoner_overlay_key(
            "g", {**_brief(), "decision_type": "chain_reaction"}
        )
        assert main_key in main._reasoner_overlays
        assert reactive_key not in main._reasoner_overlays
        assert main._reasoner_overlays.get(reactive_key) is None
    finally:
        main._reasoner_overlays.clear()
        main._reasoner_overlays.update(old_overlays)
        main._memory = old_memory
        main._reasoner_enabled = old_enabled
