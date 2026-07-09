"""Think/format flow for the goal strategist.

Covers model detection, reasoning-model kwarg handling, and the two-phase
(think → format) flow that produces a GoalSet from free-form reasoning.
"""
from __future__ import annotations

import asyncio

from ai_agent import agent as agent_module
from ai_agent import skills as skill_module
from ai_agent import strategist as strategist_module
from ai_agent.strategist import _chat_kwargs, _request_goals


# ── Fakes (mirror test_planner.py) ────────────────────────────────────────────


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, *, content=None, tool_calls=None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage) -> None:
        self.choices = [_FakeChoice(message)]
        self.usage = None


class _FakeCompletions:
    def __init__(self, scripted: list[_FakeMessage]) -> None:
        self._scripted = scripted
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._scripted.pop(0))


class _FakeChat:
    def __init__(self, scripted: list[_FakeMessage]) -> None:
        self.completions = _FakeCompletions(scripted)


class _FakeClient:
    def __init__(self, scripted: list[_FakeMessage]) -> None:
        self.chat = _FakeChat(scripted)


_STATE = {"turn_number": 3, "my_score": 2, "opponent_score": 1}

_GOAL_JSON = (
    '{"schema_version": "1.0", "turn": 3, "rationale": "contest control", '
    '"goals": [{"id": "g1", "kind": "weight_bias", '
    '"feature": "battlefield_control", "priority": "high"}]}'
)


# ── Model detection / gating ──────────────────────────────────────────────────


def test_is_reasoning_model():
    for m in ("o1", "o1-mini", "o3-mini", "o4", "gpt-5", "gpt-5-mini"):
        assert agent_module._is_reasoning_model(m) is True
    for m in ("gpt-4o", "gpt-4o-mini", "gpt-4-turbo", ""):
        assert agent_module._is_reasoning_model(m) is False


def test_chat_kwargs_drops_temperature_for_reasoning_models():
    out = _chat_kwargs(model="o1-mini", temperature=0.1, messages=[])
    assert "temperature" not in out
    out2 = _chat_kwargs(model="gpt-4o", temperature=0.1, messages=[])
    assert out2["temperature"] == 0.1


# ── Two-phase flow ────────────────────────────────────────────────────────────


def test_split_flow_thinks_then_formats():
    skill_module.set_state(_STATE)
    # Round 0 forces evaluate_position (no scout lines); then free-form reasoning;
    # then the format call returns strict GoalSet JSON.
    scripted = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "evaluate_position", "{}")]),
        _FakeMessage(content="I recommend weight_bias battlefield_control at high."),
        _FakeMessage(content=_GOAL_JSON),
    ]
    client = _FakeClient(scripted)
    goal_set = asyncio.run(
        _request_goals(
            client=client,
            model="gpt-4o",
            game_id="g1",
            brief_state=_STATE,
            memory_summary="",
            has_scout_lines=False,
        )
    )
    assert len(goal_set.goals) == 1
    assert goal_set.goals[0].feature == "battlefield_control"
    # Three create calls: tool round, think answer, format answer.
    assert len(client.chat.completions.calls) == 3
    # The format call is a pure serialization call — no tools attached.
    assert "tools" not in client.chat.completions.calls[-1]
