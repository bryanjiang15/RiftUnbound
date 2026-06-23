from __future__ import annotations

import asyncio

from ai_agent import agent as agent_module
from ai_agent import planner as planner_module
from ai_agent import skills as skill_module
from ai_agent.planner import (
    Planner,
    _planner_state_summary,
    _request_plan,
)
from ai_agent.schemas import Plan


def _make_planner_with_fake_request(monkeypatch):
    """Return (planner, call_counter) where _request_plan is stubbed (no API)."""
    calls = {"n": 0}

    async def _fake_request_plan(**kwargs):
        calls["n"] += 1
        return Plan(
            intent=f"plan-{calls['n']}",
            plan_for_turn="stub",
            priority_order=["x"],
        )

    monkeypatch.setattr(planner_module, "_request_plan", _fake_request_plan)
    return Planner(), calls


def _plan_args(turn: int, opp_count: int):
    return dict(
        client=None,
        model="m",
        game_id="g1",
        brief_state={"turn_number": turn},
        memory_summary="",
        opponent_action_count=opp_count,
    )


def test_plan_reused_within_turn_when_opponent_only_passes(monkeypatch):
    planner, calls = _make_planner_with_fake_request(monkeypatch)
    # Same turn, opponent action count unchanged (passes/moves don't bump it).
    p1, cached1 = asyncio.run(planner.plan(**_plan_args(3, 0)))
    p2, cached2 = asyncio.run(planner.plan(**_plan_args(3, 0)))
    assert calls["n"] == 1
    assert cached1 is False and cached2 is True
    assert p1.intent == p2.intent


def test_plan_invalidated_when_opponent_plays_or_uses_ability(monkeypatch):
    planner, calls = _make_planner_with_fake_request(monkeypatch)
    asyncio.run(planner.plan(**_plan_args(3, 0)))
    # Opponent played a card / used an ability → count increments → fresh plan.
    _, cached = asyncio.run(planner.plan(**_plan_args(3, 1)))
    assert calls["n"] == 2
    assert cached is False


def test_plan_invalidated_on_new_turn(monkeypatch):
    planner, calls = _make_planner_with_fake_request(monkeypatch)
    asyncio.run(planner.plan(**_plan_args(3, 0)))
    _, cached = asyncio.run(planner.plan(**_plan_args(4, 0)))
    assert calls["n"] == 2
    assert cached is False


def test_plan_intent_is_freeform_string():
    plan = Plan(
        intent="snowball-battlefield-a-with-deathknell",
        plan_for_turn="Anchor on cemetery-attendant to hold battlefield-a.",
        priority_order=["hold battlefield-a", "develop noxus-hopeful"],
    )
    assert plan.intent == "snowball-battlefield-a-with-deathknell"


_RICH_STATE = {
    "game_id": "g1",
    "turn_number": 3,
    "my_player_index": 0,
    "turn_player_index": 0,
    "current_phase": "main",
    "current_state": "neutral_open",
    "decision_type": "main_phase",
    "my_score": 2,
    "opponent_score": 1,
    "my_energy": 0,
    "my_power": {},
    "my_runes": [{"rune_index": 0, "domain": "fury", "is_exhausted": False}],
    "my_hand": [
        {
            "instance_id": "cemetery-attendant-2",
            "name": "Cemetery Attendant",
            "card_type": "unit",
            "energy_cost": 2,
            "power_cost": [],
            "might": 3,
            "keywords": ["deathknell"],
            "effect_text": "Deathknell: deal 2 damage.",
        }
    ],
    "my_base_units": [],
    "opponent_base_units": [],
    "opponent_hand_size": 4,
    "battlefields": [
        {
            "battlefield_id": "battlefield-a",
            "display_name": "Ruins",
            "controller_index": -1,
            "my_units": [],
            "opponent_units": [],
            "is_contested": False,
            "has_facedown": False,
        }
    ],
    "legal_moves": ["play cemetery-attendant-2", "end turn"],
    "pending_choice_options": ["x"],
}


def test_planner_state_summary_is_rich_and_strips_decision_local_noise():
    summary = _planner_state_summary(_RICH_STATE)
    # Rich card detail the old thin summary lacked.
    assert "Cemetery Attendant" in summary
    assert "Deathknell" in summary
    # Decision-local noise must be stripped so the turn plan is not biased by it.
    assert "end turn" not in summary
    assert "PENDING CHOICE" not in summary


# ── ReAct tool-loop test doubles ──────────────────────────────────────────────


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


def test_request_plan_runs_react_tool_loop_then_emits_plan():
    skill_module.set_state(_RICH_STATE)
    plan_json = (
        '{"schema_version": "2.0", "intent": "pressure_battlefield", '
        '"plan_for_turn": "Take battlefield-a with cemetery-attendant-2.", '
        '"priority_order": ["play cemetery-attendant-2", "hold battlefield-a"], '
        '"anchor_cards": ["cemetery-attendant-2"]}'
    )
    scripted = [
        _FakeMessage(
            tool_calls=[_FakeToolCall("c1", "evaluate_position", "{}")]
        ),
        _FakeMessage(content=plan_json),
    ]
    client = _FakeClient(scripted)

    plan = asyncio.run(
        _request_plan(
            client=client,
            model="test-model",
            game_id="g1",
            brief_state=_RICH_STATE,
            memory_summary="",
            last_intent=None,
        )
    )

    assert plan.intent == "pressure_battlefield"
    assert "cemetery-attendant-2" in plan.anchor_cards
    # The tool was offered and the loop made two model calls (tool round + plan).
    assert client.chat.completions.calls[0]["tools"]
    assert len(client.chat.completions.calls) == 2
    # Round 0 forces evaluate_position so the intent is grounded; round 1 is auto.
    assert client.chat.completions.calls[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "evaluate_position"},
    }
    assert client.chat.completions.calls[1]["tool_choice"] == "auto"


def test_request_plan_falls_back_when_schema_never_matches():
    skill_module.set_state(_RICH_STATE)
    scripted = [_FakeMessage(content="not json") for _ in range(8)]
    client = _FakeClient(scripted)

    plan = asyncio.run(
        _request_plan(
            client=client,
            model="test-model",
            game_id="g1",
            brief_state=_RICH_STATE,
            memory_summary="",
            last_intent=None,
        )
    )

    assert plan.intent == "flexible_response"
    assert plan.tactical_flexibility == "high"


def test_request_plan_logs_tool_trace_as_planner_stage(tmp_path, monkeypatch):
    skill_module.set_state(_RICH_STATE)
    monkeypatch.setattr(agent_module, "_TOOLS_LOG_PATH", tmp_path / "agent_tools.log")
    monkeypatch.setattr(agent_module, "_LOG_INPUTS", True)

    plan_json = (
        '{"schema_version": "2.0", "intent": "pressure_battlefield", '
        '"plan_for_turn": "Take battlefield-a.", '
        '"priority_order": ["play cemetery-attendant-2"]}'
    )
    scripted = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "evaluate_position", "{}")]),
        _FakeMessage(content=plan_json),
    ]
    client = _FakeClient(scripted)

    asyncio.run(
        _request_plan(
            client=client,
            model="test-model",
            game_id="g1",
            brief_state=_RICH_STATE,
            memory_summary="",
            last_intent=None,
        )
    )

    content = (tmp_path / "agent_tools.log").read_text(encoding="utf-8")
    assert "Stage: planner" in content
    assert "evaluate_position" in content
    assert "intent='pressure_battlefield'" in content
