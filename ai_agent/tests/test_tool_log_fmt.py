"""Unit tests for Claude/Cursor-style tool-call log formatters."""
from __future__ import annotations

from ai_agent.tool_log_fmt import (
    format_tool_call_lines,
    format_tools_session,
    summarize_tool_result,
)


def _strip_ansi(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\033":
            j = text.find("m", i)
            i = len(text) if j < 0 else j + 1
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def test_summarize_search_for():
    summary = summarize_tool_result(
        "search_for",
        {
            "matches": [{"line_id": "line-1", "satisfaction": 1.0}],
            "corpus_size": 5,
            "source": "live_engine",
        },
    )
    assert "matches=1" in summary
    assert "top=line-1" in summary
    assert "source=live_engine" in summary


def test_summarize_simulate():
    summary = summarize_tool_result(
        "simulate_line",
        {"legal": True, "source": "live_engine", "resolved_if_unanswered": {"x": 1}},
    )
    assert "legal=True" in summary
    assert "resolved✓" in summary


def test_format_tool_call_block_has_bullet_and_result():
    lines = format_tool_call_lines({
        "round": 1,
        "name": "search_turn",
        "args": {"top_n": 5},
        "summary": "lines=3 top=line-1",
    })
    plain = "\n".join(_strip_ansi(l) for l in lines)
    assert "● search_turn" in plain
    assert "top_n:" in plain
    assert "⎿ lines=3 top=line-1" in plain


def test_format_tools_session_outcome():
    lines = format_tools_session(
        stage="strategist",
        turn=3,
        decision_type="main_phase",
        state="Neutral Open",
        game_id="g1",
        ts="2026-01-01T00:00:00Z",
        tool_trace=[{
            "round": 0,
            "name": "evaluate_position",
            "args": {},
            "summary": "score_advantage=1",
        }],
        outcome="goals=2 (split; after 1 tool call(s))",
    )
    plain = "\n".join(_strip_ansi(l) for l in lines)
    assert "strategist" in plain
    assert "● evaluate_position" in plain
    assert "→ goals=2" in plain


def test_format_reasoner_session_includes_recommendation_and_final_output():
    lines = format_tools_session(
        stage="reasoner",
        turn=2,
        decision_type="main_phase",
        state="Neutral Open",
        game_id="g1",
        ts="2026-01-01T00:00:00Z",
        tool_trace=[],
        outcome="emit=line after 2 tool call(s)",
        reasoning="The simulated scoring line is clearly best.",
        final_output={
            "kind": "line",
            "confidence": "commit",
            "moves": ["play card-1", "end turn"],
        },
    )
    plain = "\n".join(_strip_ansi(line) for line in lines)
    assert "Reasoner recommendation:" in plain
    assert "The simulated scoring line is clearly best." in plain
    assert "Final output:" in plain
    assert '"kind": "line"' in plain
    assert "play card-1" in plain
