from __future__ import annotations

from ai_agent.router import route


def test_route_short_circuits_forced_move():
    brief = {
        "decision_type": "main_phase",
        "current_state": "neutral_open",
        "legal_moves": ["end turn"],
    }
    r = route(brief)
    assert r.forced_command == "end turn"
    assert not r.needs_plan
    assert not r.strict_plan_check


def test_route_enables_plan_for_main_phase():
    brief = {
        "decision_type": "main_phase",
        "current_state": "neutral_open",
        "legal_moves": ["play a", "end turn"],
    }
    r = route(brief)
    assert r.needs_plan
    assert r.strict_plan_check
    assert "core_rules" in r.modules
    assert "output_contract" in r.modules


def test_route_skips_plan_for_pending_choice():
    brief = {
        "decision_type": "pending_choice",
        "current_state": "neutral_open",
        "legal_moves": ["choose x", "choose y"],
    }
    r = route(brief)
    assert not r.needs_plan
    assert not r.strict_plan_check
