from __future__ import annotations

import importlib

from ai_agent import agent as agent_module
from ai_agent.schemas import Plan


def test_log_plan_writes_entry(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_plans.log"
    monkeypatch.setattr(agent_module, "_PLAN_LOG_PATH", log_path)
    monkeypatch.setattr(agent_module, "_LOG_INPUTS", True)

    plan = Plan(
        intent="develop_board",
        plan_for_turn="Develop board presence.",
        priority_order=["board_presence"],
    )
    brief_state = {"turn_number": 3, "decision_type": "main_phase"}

    agent_module._log_plan(
        "game-1", brief_state, plan, was_cached=False, decision_index=2
    )

    content = log_path.read_text(encoding="utf-8")
    assert "Turn 3" in content
    assert "main_phase" in content
    assert "Decision #: 2" in content
    assert "FRESH (new planner call)" in content
    assert "develop_board" in content


def test_log_plan_disabled_writes_nothing(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_plans.log"
    monkeypatch.setattr(agent_module, "_PLAN_LOG_PATH", log_path)
    monkeypatch.setattr(agent_module, "_LOG_INPUTS", False)

    plan = Plan(
        intent="develop_board",
        plan_for_turn="Develop board presence.",
        priority_order=["board_presence"],
    )
    agent_module._log_plan("game-1", {"turn_number": 1}, plan, was_cached=True)

    assert not log_path.exists()
