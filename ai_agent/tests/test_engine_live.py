"""Phase 2 — engine_client + live-skill fail-safe tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ai_agent import engine_client
from ai_agent import skills


# ── engine_client helpers ─────────────────────────────────────────────────────


def test_base_url_default_port(monkeypatch):
    monkeypatch.delenv("RIFTBOUND_ENGINE_PORT", raising=False)
    assert engine_client.base_url() == "http://127.0.0.1:8766"


def test_base_url_env_port(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_ENGINE_PORT", "9999")
    assert engine_client.base_url() == "http://127.0.0.1:9999"


def test_health_false_when_unreachable(monkeypatch):
    monkeypatch.setenv("RIFTBOUND_ENGINE_PORT", "1")  # nothing listening
    assert engine_client.health() is False


# ── simulate fail-safe ────────────────────────────────────────────────────────


def test_simulate_move_prefers_live_engine():
    skills.set_state({"legal_moves": ["pass"], "move_simulations": {}})
    live = {
        "legal": True,
        "applied_moves": ["pass"],
        "resolved_if_unanswered": {"score_delta": 0},
        "opponent_windows": [{"kind": "chain"}],
    }
    with patch("ai_agent.engine_client.simulate", return_value=live):
        out = skills.simulate_move({"action": "pass", "parameters": {}})
    assert out["source"] == "live_engine"
    assert out["legal"] is True
    assert out["response_window"]["kind"] == "chain"


def test_simulate_move_falls_back_to_presim():
    skills.set_state({
        "legal_moves": ["pass"],
        "move_simulations": {
            "pass": {"legal": True, "resolved_if_unanswered": {"ok": True}},
        },
    })
    with patch("ai_agent.engine_client.simulate", side_effect=engine_client.EngineUnavailable("down")):
        out = skills.simulate_move({"action": "pass", "parameters": {}})
    assert out["source"] == "presim_lookup"
    assert out["legal"] is True
    assert out["resolved_if_unanswered"]["ok"] is True


def test_simulate_line_live():
    skills.set_state({"line_simulations": {}})
    live = {"legal": True, "applied_moves": ["pass", "end turn"], "stopped_reason": "quiescence"}
    with patch("ai_agent.engine_client.simulate", return_value=live):
        out = skills.simulate_line([
            {"action": "pass", "parameters": {}},
            {"action": "end_turn", "parameters": {}},
        ])
    assert out["source"] == "live_engine"
    assert out["applied_moves"] == ["pass", "end turn"]


# ── search_for live vs corpus ─────────────────────────────────────────────────


def _corpus_line() -> dict:
    return {
        "line_id": "line-1",
        "moves": ["pass", "end turn"],
        "score": 1.0,
        "search_state": {
            "units": {},
            "battlefields": {},
            "players": {
                "me": {"score": 3, "cards_in_hand": 4, "ready_runes": 1},
                "opponent": {"score": 2, "cards_in_hand": 5, "ready_runes": 2},
            },
            "turn": {"points_scored": 1, "enemy_units_killed": 0, "battlefields_conquered": 0},
            "cards_played": [],
        },
    }


def test_search_for_uses_live_corpus():
    skills.set_search_corpus([])
    live_line = _corpus_line()
    live_line["search_state"]["turn"]["points_scored"] = 2
    with patch("ai_agent.engine_client.search", return_value={
        "legal": True,
        "candidate_lines": [live_line],
    }):
        out = skills.search_for([
            {"metric": "points_scored", "comparator": ">=", "threshold": 2},
        ])
    assert out["source"] == "live_engine"
    assert len(out["matches"]) == 1
    assert out["matches"][0]["line_id"] == "line-1"


def test_search_for_falls_back_to_presim_corpus():
    skills.set_search_corpus([_corpus_line()])
    with patch("ai_agent.engine_client.search", side_effect=engine_client.EngineUnavailable("down")):
        out = skills.search_for([
            {"metric": "points_scored", "comparator": ">=", "threshold": 1},
        ])
    assert out["source"] == "presim_corpus"
    assert len(out["matches"]) == 1


# ── deepen ────────────────────────────────────────────────────────────────────


def test_deepen_budget_and_seed_from_line_id():
    skills.set_search_corpus([{
        "line_id": "line-1",
        "moves": ["move vi-1 to battlefield-b", "play gust-1", "end turn"],
        "score": 1.0,
        "search_state": {},
    }])
    captured = {}

    def _fake_search(payload):
        captured.update(payload)
        return {
            "legal": True,
            "candidate_lines": [{"line_id": "line-1", "moves": payload["seed_moves"] + ["end turn"]}],
            "search_stats": {},
        }

    with patch("ai_agent.engine_client.search", side_effect=_fake_search):
        out = skills.deepen(line_id="line-1", extra_depth=4)

    assert out["source"] == "live_engine"
    assert captured["seed_moves"] == ["move vi-1 to battlefield-b", "play gust-1"]
    assert captured["budget"]["max_depth"] == 10  # 6 + 4
    assert captured["budget"]["node_budget"] == 80 + 4 * 40
    assert out["seed_moves"] == captured["seed_moves"]


def test_deepen_requires_engine():
    skills.set_search_corpus([{
        "line_id": "line-1",
        "moves": ["pass", "end turn"],
        "score": 1.0,
        "search_state": {},
    }])
    with patch("ai_agent.engine_client.search", side_effect=engine_client.EngineUnavailable("down")):
        out = skills.deepen(line_id="line-1")
    assert out["source"] == "unavailable"
    assert out["legal"] is False


def test_deepen_unknown_line():
    skills.set_search_corpus([])
    out = skills.deepen(line_id="line-missing")
    assert out["legal"] is False
    assert "line_id" in out["error"]
