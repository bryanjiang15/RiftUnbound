"""Phase 1: search-grounded strategist plumbing.

Covers the scout-search → strategist path that does NOT touch the LLM:
- the search_turn skill accessor over injected scout lines,
- agent._summarize_lines_for_strategist compaction,
- the grounding-tool selection (search_turn when scout lines exist, else
  evaluate_position).
"""
from __future__ import annotations

from ai_agent import agent as agent_module
from ai_agent import skills as skill_module
from ai_agent.schemas import CandidateLine, ResponseWindow


def _make_lines() -> list[CandidateLine]:
    return [
        CandidateLine(
            line_id="line-1",
            moves=["play noxus-hopeful to battlefield-a", "end turn"],
            score=5.0,
            score_breakdown={"battlefield_control": 3.0, "tempo": 1.0, "noise": 0.1},
        ),
        CandidateLine(
            line_id="line-2",
            moves=["end turn"],
            score=9.0,
            score_breakdown={"battlefield_control": 6.0, "tempo": -0.5},
            opponent_windows=[ResponseWindow()],
        ),
    ]


def test_search_turn_empty_without_scout():
    skill_module.set_search_context(None)
    out = skill_module.search_turn()
    assert out["lines"] == []
    assert "No scout search" in out["note"]


def test_summarize_lines_orders_and_trims_terms():
    summaries = agent_module._summarize_lines_for_strategist(_make_lines(), top_terms=2)
    # Best score first.
    assert [s["line_id"] for s in summaries] == ["line-2", "line-1"]
    # Only the strongest-magnitude terms are kept.
    assert set(summaries[0]["top_score_terms"]) == {"battlefield_control", "tempo"}
    # Contested flag reflects opponent windows.
    assert summaries[0]["contested"] is True
    assert summaries[1]["contested"] is False
    assert summaries[1]["moves"][0].startswith("play noxus-hopeful")


def test_search_turn_serves_injected_summaries():
    summaries = agent_module._summarize_lines_for_strategist(_make_lines())
    skill_module.set_search_context(summaries, {"nodes_explored": 42})
    out = skill_module.search_turn(top_n=1)
    assert len(out["lines"]) == 1
    assert out["lines"][0]["line_id"] == "line-2"
    assert out["search_stats"]["nodes_explored"] == 42
    skill_module.set_search_context(None)


def test_search_turn_dispatch_routes_through_agent():
    summaries = agent_module._summarize_lines_for_strategist(_make_lines())
    skill_module.set_search_context(summaries)
    result = agent_module._dispatch_tool("search_turn", {"top_n": 5})
    assert [ln["line_id"] for ln in result["lines"]] == ["line-2", "line-1"]
    skill_module.set_search_context(None)


def test_search_turn_tool_is_registered():
    names = {t["function"]["name"] for t in agent_module.TOOLS}
    assert "search_turn" in names
