"""Single-line short-circuit in the search selection path.

When TurnSearch yields exactly one committable line there is nothing to choose,
so choose_line must skip the LLM selector entirely and return that line, and the
argmax helper must still work. These tests exercise the no-LLM paths.
"""
from __future__ import annotations

import asyncio

from ai_agent import agent as agent_module
from ai_agent import skills as skill_module
from ai_agent.agent import _single_playable_line, choose_line
from ai_agent.memory import Memory
from ai_agent.schemas import CandidateLine


def _line(line_id: str, moves: list[str], score: float) -> CandidateLine:
    return CandidateLine(line_id=line_id, moves=moves, score=score)


_STATE = {"turn_number": 3, "my_player_index": 0, "legal_moves": []}


def test_single_playable_line_returns_forced_decision():
    lines = [_line("line-1", ["play noxus-hopeful to battlefield-a"], 5.0)]
    decision = _single_playable_line(lines)
    assert decision is not None
    assert decision.selector_source == "single"
    assert decision.chosen_line_id == "line-1"
    assert decision.confidence == "high"


def test_single_playable_when_only_one_line_is_committable():
    # Two lines, but one has no moves (not committable) → still a single choice.
    lines = [
        _line("line-1", ["play noxus-hopeful to battlefield-a"], 5.0),
        _line("line-2", [], 9.0),
    ]
    decision = _single_playable_line(lines)
    assert decision is not None
    assert decision.chosen_line_id == "line-1"


def test_no_short_circuit_with_two_playable_lines():
    lines = [
        _line("line-1", ["play a to battlefield-a"], 5.0),
        _line("line-2", ["end turn"], 9.0),
    ]
    assert _single_playable_line(lines) is None


def test_choose_line_short_circuits_without_llm(tmp_path, monkeypatch):
    skill_module.set_state(_STATE)

    async def _boom(*args, **kwargs):  # must never be called
        raise AssertionError("LLM selector should not run for a single line")

    monkeypatch.setattr(agent_module, "_chat_create", _boom)
    lines = [_line("line-1", ["play noxus-hopeful to battlefield-a"], 5.0)]
    decision = asyncio.run(
        choose_line(
            brief_state=_STATE,
            game_id="g1",
            memory=Memory(db_path=tmp_path / "mem.db"),
            candidate_lines=lines,
        )
    )
    assert decision.selector_source == "single"
    assert decision.chosen_line_id == "line-1"
