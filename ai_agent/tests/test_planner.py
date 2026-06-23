from __future__ import annotations

from ai_agent.planner import strategic_state_hash


BASE = {
    "game_id": "g1",
    "turn_number": 3,
    "my_score": 2,
    "opponent_score": 1,
    "decision_type": "main_phase",
    "current_state": "neutral_open",
    "legal_moves": ["play a", "end turn"],
    "pending_choice_options": ["x"],
}


def test_strategic_hash_ignores_volatile_fields():
    a = dict(BASE)
    b = dict(BASE)
    b["legal_moves"] = ["pass"]
    b["pending_choice_options"] = ["y", "z"]
    b["decision_type"] = "pending_choice"
    assert strategic_state_hash(a) == strategic_state_hash(b)


def test_strategic_hash_changes_when_board_state_changes():
    a = dict(BASE)
    b = dict(BASE)
    b["my_score"] = 3
    assert strategic_state_hash(a) != strategic_state_hash(b)
