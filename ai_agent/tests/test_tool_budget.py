from __future__ import annotations

from unittest.mock import patch

from ai_agent import skills
from ai_agent.tool_budget import ToolBudget, install_budget, reset_budget


def test_search_budget_clamps_and_exhausts():
    budget = ToolBudget(node_limit=10, time_limit_ms=1000)
    payload = budget.clamp_search_payload({
        "budget": {"node_budget": 50, "time_budget_ms": 5000}
    })
    assert payload is not None
    assert payload["budget"]["node_budget"] == 10
    assert payload["budget"]["time_budget_ms"] <= 1000

    budget.record_search(
        {"search_stats": {"nodes_explored": 10, "elapsed_ms": 5}},
        elapsed_ms=5,
        requested_nodes=10,
    )
    assert budget.exhausted is True
    assert budget.remaining_pct == 0


def test_simulate_is_memoized_within_budget_context():
    budget = ToolBudget()
    token = install_budget(budget)
    try:
        with patch(
            "ai_agent.engine_client.simulate",
            return_value={"legal": True, "applied_moves": ["pass"]},
        ) as call:
            first = skills.simulate_line(["pass"])
            second = skills.simulate_line(["pass"])
    finally:
        reset_budget(token)

    assert first["source"] == "live_engine"
    assert second["source"] == "live_engine"
    assert second["cached"] is True
    assert "budget_remaining_pct" in second
    assert call.call_count == 1
