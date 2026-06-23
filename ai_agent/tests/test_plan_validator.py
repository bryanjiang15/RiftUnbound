from __future__ import annotations

from ai_agent.agent import _plan_consistency_failure_reason
from ai_agent.schemas import Decision, Move, Plan, TargetProfile


def test_plan_consistency_rejects_wrong_battlefield_focus():
    plan = Plan(
        intent="pressure_battlefield",
        plan_for_turn="Pressure battlefield-a.",
        priority_order=["battlefield_pressure"],
        focus_battlefields=["battlefield-a"],
        target_profile=TargetProfile(kind="battlefield", ids=["battlefield-a"]),
        tactical_flexibility="low",
    )
    reason = _plan_consistency_failure_reason(
        decision=Decision(
            reasoning="move for pressure",
            move=Move(action="move_unit", parameters={"unit_ids": ["u1"], "destination": "battlefield-b"}),
        ),
        brief_state={"decision_type": "main_phase"},
        plan=plan,
        strict_plan_check=True,
    )
    assert reason


def test_plan_consistency_allows_high_flexibility():
    plan = Plan(
        intent="flexible_response",
        plan_for_turn="Keep options open.",
        priority_order=["legality"],
        focus_battlefields=["battlefield-a"],
        tactical_flexibility="high",
    )
    reason = _plan_consistency_failure_reason(
        decision=Decision(
            reasoning="respond tactically",
            move=Move(action="move_unit", parameters={"unit_ids": ["u1"], "destination": "battlefield-b"}),
        ),
        brief_state={"decision_type": "showdown_focus"},
        plan=plan,
        strict_plan_check=True,
    )
    assert reason is None
