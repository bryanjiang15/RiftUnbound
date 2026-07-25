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


def test_log_tools_writes_trace_and_outcome(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_search.log"
    monkeypatch.setattr(agent_module, "_SEARCH_LOG_PATH", log_path)
    monkeypatch.setattr(agent_module, "_LOG_INPUTS", True)

    brief_state = {
        "turn_number": 4,
        "decision_type": "main_phase",
        "current_state": "neutral_open",
    }
    agent_module._log_tools(
        "game-1",
        brief_state,
        tool_trace=[
            {"round": 0, "name": "evaluate_position", "args": {}},
            {"round": 1, "name": "get_card_detail", "args": {"card_id": "x-1"}},
        ],
        outcome="pass (validator budget exhausted; last reason: not legal)",
    )

    content = log_path.read_text(encoding="utf-8")
    assert "Turn 4" in content
    assert "neutral_open" in content
    assert "Tool calls (2):" in content
    assert "evaluate_position" in content
    assert "get_card_detail" in content
    assert "validator budget exhausted" in content


def test_log_tools_skips_when_no_tools_called(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_search.log"
    monkeypatch.setattr(agent_module, "_SEARCH_LOG_PATH", log_path)
    monkeypatch.setattr(agent_module, "_LOG_INPUTS", True)

    agent_module._log_tools(
        "game-1",
        {"turn_number": 1, "decision_type": "main_phase", "current_state": "x"},
        tool_trace=[],
        outcome="play_card (after 0 tool call(s))",
    )

    assert not log_path.exists()


def test_log_tools_disabled_writes_nothing(tmp_path, monkeypatch):
    log_path = tmp_path / "agent_search.log"
    monkeypatch.setattr(agent_module, "_SEARCH_LOG_PATH", log_path)
    monkeypatch.setattr(agent_module, "_LOG_INPUTS", False)

    agent_module._log_tools(
        "game-1",
        {"turn_number": 1},
        tool_trace=[{"round": 0, "name": "evaluate_position", "args": {}}],
        outcome="pass",
    )

    assert not log_path.exists()
