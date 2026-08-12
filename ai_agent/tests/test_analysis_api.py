"""Analysis UI list/detail helpers and FastAPI route shapes."""
from __future__ import annotations

from fastapi.testclient import TestClient

from ai_agent.memory import Memory
from ai_agent import main as main_mod


def _seed(mem: Memory) -> None:
    mem.record(
        game_id="g1",
        turn=3,
        decision_type="main_phase",
        brief_state={"turn_number": 3},
        reasoning="play something",
        move={"action": "play_card", "parameters": {"card_id": "vi-destructive"}},
        accepted=True,
    )
    # record() assigns decision_index=0 for first row
    analysis = {
        "schema_version": "1",
        "replay": {"supported": True, "reason": ""},
        "cards": {},
        "players": [],
        "board": {},
    }
    mem.record_decision_snapshot(
        game_id="g1",
        turn=3,
        decision_index=0,
        scalars={
            "my_score": 2,
            "opp_score": 1,
            "my_energy": 3,
            "board_might_diff": 0,
            "cards_in_hand": 4,
            "cards_in_hand_opp": 5,
            "bf_control_net": 0,
        },
        brief_state={"turn_number": 3},
        analysis_state=analysis,
        analysis_state_schema_version="1",
        root_state_hash="abc123",
    )
    mem.record_search_decision(
        game_id="g1",
        turn=3,
        decision_index=0,
        decision_type="main_phase",
        mode="main",
        my_player_index=0,
        chosen_line_id="L0",
        chosen_line_score=1.5,
        best_candidate_score=1.5,
        regret=0.0,
        score_margin=0.2,
        num_candidates=1,
        chosen_breakdown=None,
        chosen_features=None,
        search_stats={"mode": "main"},
        selector_source="argmax",
        selector_reasoning="best",
        origin="live",
        weight_version_id=None,
        candidates=[{
            "line_id": "L0",
            "rank": 0,
            "score": 1.5,
            "chosen": True,
            "moves": ["play vi-destructive", "end turn"],
            "breakdown": {},
            "features": {},
            "resolved_state": {},
            "search_state": {},
        }],
    )

    # Non-replayable decision in another game
    mem.record(
        game_id="g2",
        turn=1,
        decision_type="mulligan",
        brief_state={"turn_number": 1},
        reasoning="keep",
        move={"action": "mulligan_keep", "parameters": {}},
        accepted=True,
    )
    mem.record_decision_snapshot(
        game_id="g2",
        turn=1,
        decision_index=0,
        scalars={},
        brief_state={"turn_number": 1},
        analysis_state={
            "schema_version": "1",
            "replay": {"supported": False, "reason": "mulligan"},
        },
        analysis_state_schema_version="1",
        root_state_hash="def",
    )


def test_list_decisions_filters_and_fields(tmp_path):
    mem = Memory(db_path=tmp_path / "mem.db")
    _seed(mem)

    all_rows = mem.list_decisions(limit=50)
    assert len(all_rows) == 2
    by_game = {r["game_id"]: r for r in all_rows}
    assert by_game["g1"]["action"] == "play_card"
    assert by_game["g1"]["card_id"] == "vi-destructive"
    assert by_game["g1"]["has_analysis_state"] is True
    assert by_game["g1"]["replay_supported"] is True
    assert by_game["g1"]["selector_source"] == "argmax"
    assert by_game["g2"]["replay_supported"] is False

    replay_only = mem.list_decisions(replay_only=True)
    assert len(replay_only) == 1
    assert replay_only[0]["game_id"] == "g1"

    g1 = mem.list_decisions(game_id="g1")
    assert len(g1) == 1


def test_analysis_decision_detail_shape(tmp_path):
    mem = Memory(db_path=tmp_path / "mem.db")
    _seed(mem)
    detail = main_mod._analysis_decision_detail(
        mem, game_id="g1", turn=3, decision_index=0,
    )
    assert detail["seat"] == 0
    assert detail["episodic"]["move"]["action"] == "play_card"
    assert detail["snapshot"]["analysis_state"]["replay"]["supported"] is True
    assert detail["root_state_hash"] == "abc123"
    assert detail["candidates"][0]["moves"] == ["play vi-destructive", "end turn"]
    assert detail["snapshot"]["analysis_state_json"] is None


def test_analysis_http_list_and_detail(tmp_path, monkeypatch):
    mem = Memory(db_path=tmp_path / "mem.db")
    _seed(mem)
    monkeypatch.setattr(main_mod, "_memory", mem)

    client = TestClient(main_mod.app)
    listed = client.get("/analysis/decisions", params={"replay_only": True})
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] == 1
    assert body["decisions"][0]["game_id"] == "g1"

    detail = client.get(
        "/analysis/decision",
        params={"game_id": "g1", "turn": 3, "decision_index": 0},
    )
    assert detail.status_code == 200
    d = detail.json()
    assert d["candidates"][0]["line_id"] == "L0"
    assert isinstance(d["snapshot"]["analysis_state"], dict)

    missing = client.get(
        "/analysis/decision",
        params={"game_id": "missing", "turn": 0, "decision_index": 0},
    )
    assert missing.status_code == 404

    status = client.get("/analysis/db-status")
    assert status.status_code == 200
    assert "ready_for_counterfactual" in status.json()


def test_analysis_http_run_endpoints_mock(tmp_path, monkeypatch):
    mem = Memory(db_path=tmp_path / "mem.db")
    _seed(mem)
    monkeypatch.setattr(main_mod, "_memory", mem)

    fake_cf = {
        "ok": True,
        "status": "ok",
        "game_id": "g1",
        "turn": 3,
        "decision_index": 0,
        "comparison": {"offline_best": {"canonical_moves": ["pass", "end turn"]}},
    }
    fake_report = {"modes": ["selection"], "summary": "ok"}

    monkeypatch.setattr(
        "ai_agent.analysis.counterfactual.analyze_decision",
        lambda *a, **k: fake_cf,
    )
    monkeypatch.setattr(
        "ai_agent.analysis.counterfactual.render_markdown",
        lambda r: "# CF\nok",
    )
    monkeypatch.setattr(
        "ai_agent.analysis.failure_modes.classify_with_counterfactual",
        lambda bundle, cf_result: fake_report,
    )
    monkeypatch.setattr(
        "ai_agent.analysis.failure_modes.render_markdown",
        lambda r: "# Fail\nok",
    )

    client = TestClient(main_mod.app)
    cf_resp = client.post(
        "/analysis/counterfactual",
        json={"game_id": "g1", "turn": 3, "decision_index": 0, "persist": False},
    )
    assert cf_resp.status_code == 200
    assert cf_resp.json()["markdown"].startswith("# CF")
    assert cf_resp.json()["result"]["status"] == "ok"

    fr = client.post(
        "/analysis/failure-report",
        json={
            "game_id": "g1",
            "turn": 3,
            "decision_index": 0,
            "with_counterfactual": False,
            "counterfactual_result": fake_cf,
            "persist": False,
        },
    )
    assert fr.status_code == 200
    assert fr.json()["report"]["modes"] == ["selection"]
