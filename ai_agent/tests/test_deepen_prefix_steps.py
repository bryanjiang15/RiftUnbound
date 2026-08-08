from __future__ import annotations

from unittest.mock import patch

from ai_agent import skills
from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context


def test_deepen_prefix_steps_truncates_seed_moves():
    state = {"turn_number": 2, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g-prefix", state, "root")
    line = context.registry.register(
        {
            "line_id": "line-1",
            "moves": [
                "play unit-a",
                "move unit-a to battlefield-a",
                "play unit-b",
                "end turn",
            ],
            "complete": True,
            "legal": True,
            "root_state_hash": "root",
            "expected_pre_hashes": ["a", "b", "c", "d"],
            "move_contexts": [{"kind": "scripted"}] * 4,
        },
        source="scout",
    )
    context.scout_lines = [line]
    captured = {}

    def fake_search(payload):
        captured["payload"] = payload
        return {
            "candidate_lines": [
                {
                    "line_id": "line-9",
                    "moves": ["play unit-a", "move unit-a to battlefield-b", "end turn"],
                    "complete": True,
                    "legal": True,
                    "root_state_hash": "root",
                    "expected_pre_hashes": ["a", "b", "c"],
                    "move_contexts": [{"kind": "scripted"}] * 3,
                    "resolved_state": {"points_scored": 1},
                }
            ]
        }

    token = install_context(context)
    try:
        with patch("ai_agent.engine_client.search", side_effect=fake_search):
            out = skills.deepen(line_id=line["line_id"], prefix_steps=1)
    finally:
        reset_context(token)

    assert captured["payload"]["seed_moves"] == ["play unit-a"]
    assert out["prefix_steps"] == 1
    assert out["result_status"] == "evidence"
    assert out["candidate_lines"]


def test_deepen_illegal_seed_suggests_shorter_prefix():
    state = {"turn_number": 2, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g-seed", state, "root")
    token = install_context(context)
    try:
        with patch(
            "ai_agent.engine_client.search",
            return_value={
                "error": "seed move illegal: choose x",
                "stopped_reason": "seed_failed",
                "candidate_lines": [],
            },
        ):
            out = skills.deepen(
                moves=[
                    {"action": "play_card", "parameters": {"card_id": "a"}},
                    "choose x",
                ]
            )
    finally:
        reset_context(token)

    assert out["result_status"] == "illegal_seed"
    assert out["suggested_prefix"]
    assert out["legal"] is False
