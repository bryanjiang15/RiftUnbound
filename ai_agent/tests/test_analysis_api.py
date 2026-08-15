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
    assert "search_state" not in detail["candidates"][0]
    assert "features" not in detail["candidates"][0]
    assert detail["snapshot"]["analysis_state_json"] is None

    lite = main_mod._analysis_decision_detail(
        mem, game_id="g1", turn=3, decision_index=0, include_state=False,
    )
    assert lite["snapshot"]["analysis_state"] is None
    assert lite["candidates"][0]["moves"] == ["play vi-destructive", "end turn"]
    assert lite["snapshot_status"] == "ok"


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
    assert d["snapshot"]["analysis_state"] is None
    assert "search_state" not in d["candidates"][0]

    with_state = client.get(
        "/analysis/decision",
        params={"game_id": "g1", "turn": 3, "decision_index": 0, "include_state": True},
    )
    assert with_state.status_code == 200
    assert isinstance(with_state.json()["snapshot"]["analysis_state"], dict)

    checkpoint = client.get(
        "/analysis/checkpoint",
        params={"game_id": "g1", "turn": 3, "decision_index": 0},
    )
    assert checkpoint.status_code == 200
    cp = checkpoint.json()
    assert isinstance(cp["analysis_state"], dict)
    assert cp["root_state_hash"] == "abc123"
    assert "candidates" not in cp

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

    # Persisted run list endpoint (empty initially for this mock path)
    runs = client.get(
        "/analysis/counterfactual-runs",
        params={"game_id": "g1", "turn": 3, "decision_index": 0},
    )
    assert runs.status_code == 200
    assert "runs" in runs.json()


def test_counterfactual_run_list_omits_result_until_fetched(tmp_path, monkeypatch):
    mem = Memory(db_path=tmp_path / "mem.db")
    _seed(mem)
    fat_result = {
        "ok": True,
        "run_kind": "outcome_rollout",
        "candidate_lines": [{"line_id": "p", "moves": ["end turn"], "search_state": {"x": "y" * 100}}],
    }
    run_id = mem.record_counterfactual_run(
        game_id="g1",
        turn=3,
        decision_index=0,
        root_state_hash="abc123",
        predicate_pack_version=None,
        search_inputs=None,
        profile_inputs=None,
        budget={"node_budget": 1},
        assumptions={"horizon": "multi_turn"},
        status="ok",
        result=fat_result,
    )
    monkeypatch.setattr(main_mod, "_memory", mem)
    client = TestClient(main_mod.app)

    listed = client.get(
        "/analysis/counterfactual-runs",
        params={"game_id": "g1", "turn": 3, "decision_index": 0},
    )
    assert listed.status_code == 200
    rows = listed.json()["runs"]
    assert len(rows) == 1
    assert rows[0]["id"] == run_id
    assert rows[0]["result"] is None
    assert rows[0]["status"] == "ok"

    one = client.get(f"/analysis/counterfactual-runs/{run_id}")
    assert one.status_code == 200
    assert one.json()["result"]["run_kind"] == "outcome_rollout"
    assert one.json()["result"]["candidate_lines"][0]["line_id"] == "p"


def test_analysis_http_accepts_rollout_body(tmp_path, monkeypatch):
    mem = Memory(db_path=tmp_path / "mem.db")
    _seed(mem)
    monkeypatch.setattr(main_mod, "_memory", mem)

    captured = {}

    def _fake_analyze(*_a, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "status": "ok",
            "run_kind": "outcome_rollout",
            "horizon": "multi_turn",
            "future_player_turns": kwargs.get("future_player_turns", 4),
            "outcome_tiers": {"by_root": []},
        }

    monkeypatch.setattr("ai_agent.analysis.counterfactual.analyze_decision", _fake_analyze)
    monkeypatch.setattr(
        "ai_agent.analysis.counterfactual.render_markdown",
        lambda r: "# Rollout\nok",
    )
    client = TestClient(main_mod.app)
    resp = client.post(
        "/analysis/counterfactual",
        json={
            "game_id": "g1",
            "turn": 3,
            "decision_index": 0,
            "persist": False,
            "mode": "outcome_rollout",
            "preset": "fast",
            "future_player_turns": 2,
            "target": {"kind": "win"},
        },
    )
    assert resp.status_code == 200
    assert captured.get("preset") == "fast"
    assert captured.get("future_player_turns") == 2
    assert captured.get("mode") == "outcome_rollout"
    assert resp.json()["result"]["run_kind"] == "outcome_rollout"
