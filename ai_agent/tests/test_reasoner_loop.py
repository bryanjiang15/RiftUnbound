from __future__ import annotations

import asyncio

from ai_agent import reasoner
from ai_agent.tool_budget import ToolBudget, install_budget, reset_budget


class _Function:
    def __init__(self, name: str, arguments: str = "{}"):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, name: str):
        self.id = "tool-1"
        self.function = _Function(name)


class _Message:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Response:
    usage = None

    def __init__(self, message):
        self.choices = [type("Choice", (), {"message": message})()]


class _Completions:
    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.messages.pop(0))


class _Client:
    def __init__(self, messages):
        self.chat = type("Chat", (), {"completions": _Completions(messages)})()


def test_reasoner_forces_scout_grounding_then_commits_known_line():
    client = _Client([
        _Message(tool_calls=[_ToolCall("search_turn")]),
        _Message(content="The scout line is verified and clearly best."),
        _Message(content=(
            '{"kind":"line","confidence":"commit","chosen_line_id":"line-1",'
            '"moves":["pass","end turn"],"rationale":"engine-observed"}'
        )),
    ])
    emit = asyncio.run(reasoner._request_reasoning(
        client=client,
        model="gpt-4o",
        game_id="g1",
        brief_state={"turn_number": 1, "legal_moves": ["pass"]},
        memory_summary="",
        known_lines=[{"line_id": "line-1", "moves": ["pass", "end turn"]}],
    ))
    first_call = client.chat.completions.calls[0]
    assert first_call["tool_choice"]["function"]["name"] == "search_turn"
    assert emit.kind == "line"
    assert emit.chosen_line_id == "line-1"


def test_exhausted_budget_forces_text_emit_after_grounding():
    client = _Client([
        _Message(tool_calls=[_ToolCall("evaluate_position")]),
        _Message(content="No exact line is verified; hand off empty goals."),
        _Message(content=(
            '{"kind":"goals","confidence":"goals","goal_set":'
            '{"turn":1,"rationale":"base search","goals":[]},'
            '"rationale":"budget exhausted"}'
        )),
    ])
    budget = ToolBudget(time_limit_ms=1)
    budget.engine_time_ms = 1
    token = install_budget(budget)
    try:
        emit = asyncio.run(reasoner._request_reasoning(
            client=client,
            model="gpt-4o",
            game_id="g2",
            brief_state={"turn_number": 1, "legal_moves": ["pass"]},
            memory_summary="",
            known_lines=[],
        ))
    finally:
        reset_budget(token)
    assert client.chat.completions.calls[1]["tool_choice"] == "none"
    assert emit.kind == "goals"

