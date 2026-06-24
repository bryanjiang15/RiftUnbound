"""Phase 2.5 — engine-truth simulation: schema + skill-lookup tests.

These cover the Python side only (schema validation and how the skills surface
the pre-simulated facts inlined by Godot). The Godot-side clone + MoveSimulator
are exercised by the Tcg test suite.
"""
from __future__ import annotations

from ai_agent import schemas, skills


# ── Schemas ───────────────────────────────────────────────────────────────────


def test_resolved_state_defaults_and_omit_empty_roundtrip():
    rs = schemas.ResolvedState(conquer=True, my_score_after=1)
    dumped = rs.model_dump(exclude_defaults=True)
    # Only the fields we set survive an exclude-defaults dump (omit-empty wire).
    assert dumped == {"conquer": True, "my_score_after": 1}


def test_sim_result_accepts_partial_godot_dict():
    sim = schemas.SimResult.model_validate(
        {
            "legal": True,
            "resolved_if_unanswered": {
                "wins_game": False,
                "conquer": True,
                "my_score_after": 1,
                "battlefields": {
                    "battlefield-a": {
                        "controller_before": "neutral",
                        "controller_after": "me",
                    }
                },
                "trade": "I lose nothing; they lose poro-2 (2 might)",
                "units_killed": ["poro-2"],
            },
            "response_window": {
                "opponent_may_respond": True,
                "legal_response_classes": ["Reaction"],
                "opponent_unknown_cards": 4,
            },
        }
    )
    assert sim.legal is True
    assert sim.resolved_if_unanswered.conquer is True
    assert sim.resolved_if_unanswered.battlefields["battlefield-a"].controller_after == "me"
    assert sim.response_window.opponent_unknown_cards == 4


def test_line_result_first_illegal_move():
    line = schemas.LineResult.model_validate(
        {
            "legal": False,
            "applied_moves": ["move vi to battlefield-a"],
            "stopped_reason": "illegal",
            "first_illegal_move": "play decisive-strike",
        }
    )
    assert line.legal is False
    assert line.first_illegal_move == "play decisive-strike"


# ── Skill lookup (option C pre-sim) ───────────────────────────────────────────


def _install_brief(move_simulations=None, line_simulations=None, legal_moves=None):
    skills.set_state(
        {
            "legal_moves": legal_moves or [],
            "move_simulations": move_simulations or {},
            "line_simulations": line_simulations or {},
        }
    )


def test_simulate_move_returns_presimulated_fact():
    presim = {
        "legal": True,
        "resolved_if_unanswered": {"conquer": True, "my_score_after": 1},
    }
    _install_brief(move_simulations={"move vi-2 to battlefield-a": presim})
    result = skills.simulate_move(
        {"action": "move_unit", "parameters": {"unit_ids": ["vi-2"], "destination": "battlefield-a"}}
    )
    assert result["legal"] is True
    assert result["resolved_if_unanswered"]["conquer"] is True


def test_simulate_move_no_presim_does_not_invent_outcome():
    _install_brief(legal_moves=["play raging-soul"])
    result = skills.simulate_move(
        {"action": "play_card", "parameters": {"card_id": "raging-soul"}}
    )
    # Legal (it's in legal_moves) but explicitly flags no engine outcome.
    assert result["legal"] is True
    assert "error" in result
    assert "do not assert" in result["error"].lower()


def test_simulate_line_returns_presimulated_line():
    key = "move vi-2 to battlefield-a ; play decisive-strike"
    line = {
        "legal": True,
        "applied_moves": ["move vi-2 to battlefield-a", "play decisive-strike"],
        "stopped_reason": "quiescence",
        "resolved_if_unanswered": {"conquer": True, "my_score_after": 1},
        "opponent_windows": [
            {"after_move": "move vi-2 to battlefield-a", "legal_response_classes": ["Reaction"]}
        ],
    }
    _install_brief(line_simulations={key: line})
    result = skills.simulate_line(
        [
            {"action": "move_unit", "parameters": {"unit_ids": ["vi-2"], "destination": "battlefield-a"}},
            {"action": "play_card", "parameters": {"card_id": "decisive-strike"}},
        ]
    )
    assert result["legal"] is True
    assert result["opponent_windows"][0]["legal_response_classes"] == ["Reaction"]


def test_simulate_line_falls_back_to_first_move_sim():
    first = "move vi-2 to battlefield-a"
    _install_brief(
        move_simulations={
            first: {"legal": True, "resolved_if_unanswered": {"conquer": True}}
        }
    )
    result = skills.simulate_line(
        [
            {"action": "move_unit", "parameters": {"unit_ids": ["vi-2"], "destination": "battlefield-a"}},
            {"action": "play_card", "parameters": {"card_id": "decisive-strike"}},
        ]
    )
    assert result["applied_moves"] == [first]
    assert result["stopped_reason"] == "line_not_presimulated"
    assert "error" in result


def test_simulate_line_no_data_returns_not_simulated():
    _install_brief()
    result = skills.simulate_line(
        [{"action": "move_unit", "parameters": {"unit_ids": ["vi-2"], "destination": "battlefield-a"}}]
    )
    assert result["legal"] is False
    assert result["stopped_reason"] == "not_simulated"


def test_move_to_command_matches_serializer_key():
    # The lookup key must match Move.to_command() exactly.
    cmd = skills._move_to_command(
        {"action": "move_unit", "parameters": {"unit_ids": ["vi-2"], "destination": "battlefield-a"}}
    )
    assert cmd == "move vi-2 to battlefield-a"
