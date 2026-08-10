from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from ai_agent import reasoner
from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context
from ai_agent.tool_budget import ToolBudget, install_budget, reset_budget


class _Function:
    def __init__(self, name: str, arguments: str = "{}"):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    _next_id = 0

    def __init__(self, name: str, arguments: dict | None = None):
        type(self)._next_id += 1
        self.id = f"tool-{self._next_id}"
        self.function = _Function(name, json.dumps(arguments or {}))


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
        # Snapshot messages: the reasoner mutates the same list across rounds.
        recorded = dict(kwargs)
        if "messages" in recorded:
            recorded["messages"] = list(recorded["messages"])
        self.calls.append(recorded)
        return _Response(self.messages.pop(0))


class _Client:
    def __init__(self, messages):
        self.chat = type("Chat", (), {"completions": _Completions(messages)})()


def _complete_line(context: ReasonerTurnContext, source: str = "scout") -> dict:
    line = context.registry.register({
        "line_id": "line-1",
        "moves": ["pass", "end turn"],
        "move_contexts": [{"kind": "scripted"}, {"kind": "scripted"}],
        "expected_pre_hashes": ["root", "after-pass"],
        "root_state_hash": "root",
        "legal": True,
        "complete": True,
        "terminal_reason": "end_turn",
    }, source=source)
    assert line is not None
    return line


def test_reasoner_does_not_repeat_inlined_scout_before_native_commit():
    state = {"turn_number": 1, "legal_moves": ["pass"]}
    context = ReasonerTurnContext("g1", state, "root")
    line = _complete_line(context)
    context.scout_lines = [line]
    client = _Client([
        _Message(tool_calls=[_ToolCall("commit_line", {
            "line_id": line["line_id"],
            "rationale": "Forced line; scout is complete and root matched.",
        })]),
    ])
    token = install_context(context)
    try:
        emit = asyncio.run(reasoner._request_reasoning(
            client=client,
            model="gpt-4o",
            game_id="g1",
            brief_state=state,
            memory_summary="",
            known_lines=[line],
            root_state_hash="root",
        ))
    finally:
        reset_context(token)
    assert client.chat.completions.calls[0]["tool_choice"] == "auto"
    initial_user = client.chat.completions.calls[0]["messages"][1]["content"]
    assert '"steps"' in initial_user
    assert line["line_id"] in initial_user
    assert emit.kind == "line"
    assert emit.chosen_line_id == line["line_id"]


def test_investigation_gate_rejects_early_terminal_then_accepts_search():
    state = {"turn_number": 2, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g2", state, "root")
    scout = _complete_line(context)
    context.scout_lines = [scout, dict(scout, line_id="other")]
    client = _Client([
        _Message(tool_calls=[_ToolCall("commit_line", {
            "line_id": scout["line_id"],
            "rationale": "Scout is best.",
        })]),
        _Message(tool_calls=[_ToolCall("search_for", {
            "constraints": [{"metric": "points_scored", "comparator": ">=", "threshold": 1}],
        })]),
        _Message(tool_calls=[_ToolCall("commit_line", {
            "line_id": scout["line_id"],
            "rationale": "The alternative was compared with the scout; scout remains safer.",
        })]),
    ])

    def fake_tool(trace, *, round_num, name, args):
        trace.append({"round": round_num, "name": name, "args": args, "summary": "matches=1"})
        return json.dumps({
            "source": "live_engine",
            "matches": [{
                "line_id": "alt",
                "moves": ["end turn"],
                "complete": True,
            }],
        })

    token = install_context(context)
    try:
        with patch("ai_agent.agent._invoke_traced_tool", side_effect=fake_tool):
            emit = asyncio.run(reasoner._request_reasoning(
                client=client,
                model="gpt-4o",
                game_id="g2",
                brief_state=state,
                memory_summary="",
                known_lines=context.scout_lines,
                root_state_hash="root",
            ))
    finally:
        reset_context(token)
    assert emit.kind == "line"
    assert context.telemetry["investigation_satisfied"] is True
    assert context.telemetry["terminal_validation_errors"]


def test_budget_exhaustion_is_explicit_gate_exemption_for_nonempty_goals():
    state = {"turn_number": 3, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g3", state, "root")
    client = _Client([
        _Message(tool_calls=[_ToolCall("evaluate_position")]),
        _Message(tool_calls=[_ToolCall("emit_goals", {
            "goal_set": {
                "turn": 0,
                "goals": [{
                    "id": "control",
                    "kind": "weight_bias",
                    "feature": "battlefield_control",
                }],
            },
            "rationale": "Budget is exhausted; preserve battlefield control.",
        })]),
    ])
    budget = ToolBudget(time_limit_ms=1)
    budget.engine_time_ms = 1
    context.budget = budget
    context_token = install_context(context)
    budget_token = install_budget(budget)
    try:
        emit = asyncio.run(reasoner._request_reasoning(
            client=client,
            model="gpt-4o",
            game_id="g3",
            brief_state=state,
            memory_summary="",
            known_lines=[],
            root_state_hash="root",
        ))
    finally:
        reset_budget(budget_token)
        reset_context(context_token)
    assert emit.kind == "goals"
    assert emit.goal_set is not None
    assert emit.goal_set.turn == 3
    assert len(emit.goal_set.goals) == 1


def _assert_tool_replies_contiguous(messages: list[dict]) -> None:
    """OpenAI requires all tool replies immediately after an assistant tool_calls msg."""
    i = 0
    while i < len(messages):
        msg = messages[i]
        tool_calls = getattr(msg, "tool_calls", None)
        if isinstance(msg, dict):
            tool_calls = msg.get("tool_calls")
        if not tool_calls:
            i += 1
            continue
        expected_ids = [tc.id for tc in tool_calls]
        i += 1
        for tool_call_id in expected_ids:
            assert i < len(messages), f"missing tool reply for {tool_call_id}"
            reply = messages[i]
            assert isinstance(reply, dict)
            assert reply.get("role") == "tool", (
                f"expected contiguous tool reply for {tool_call_id}, "
                f"got role={reply.get('role')!r}"
            )
            assert reply.get("tool_call_id") == tool_call_id
            i += 1


def test_parallel_deepen_defers_feedback_envelopes_until_all_tool_replies():
    """Regression: user envelopes must not interrupt parallel tool_call replies."""
    state = {"turn_number": 2, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g-parallel", state, "root")
    scout = _complete_line(context)
    alt = context.registry.register({
        "line_id": "line-2",
        "moves": ["end turn"],
        "move_contexts": [{"kind": "scripted"}],
        "expected_pre_hashes": ["root"],
        "root_state_hash": "root",
        "legal": True,
        "complete": True,
        "terminal_reason": "end_turn",
    }, source="scout")
    assert alt is not None
    context.scout_lines = [scout, alt]
    deepen_a = _ToolCall(
        "deepen",
        {"line_id": scout["line_id"], "prefix_steps": 1, "extra_depth": 3},
    )
    deepen_b = _ToolCall(
        "deepen",
        {"line_id": alt["line_id"], "prefix_steps": 1, "extra_depth": 3},
    )
    client = _Client([
        _Message(tool_calls=[deepen_a, deepen_b]),
        _Message(tool_calls=[_ToolCall("commit_line", {
            "line_id": scout["line_id"],
            "rationale": (
                "Compared with scout; deepened both frontiers and kept the safer line."
            ),
        })]),
    ])

    def fake_tool(trace, *, round_num, name, args):
        trace.append({"round": round_num, "name": name, "args": args, "summary": name})
        line_id = args.get("line_id")
        moves = (
            list(scout["moves"]) if line_id == scout["line_id"] else list(alt["moves"])
        )
        return json.dumps({
            "source": "live_engine",
            "candidate_lines": [{
                "line_id": line_id,
                "moves": moves,
                "complete": True,
                "resolved_state": {"points_scored": 0, "hand_size": 4},
            }],
        })

    token = install_context(context)
    try:
        with patch("ai_agent.agent._invoke_traced_tool", side_effect=fake_tool):
            emit = asyncio.run(reasoner._request_reasoning(
                client=client,
                model="gpt-4o",
                game_id="g-parallel",
                brief_state=state,
                memory_summary="",
                known_lines=context.scout_lines,
                root_state_hash="root",
            ))
    finally:
        reset_context(token)

    assert emit.kind == "line"
    assert len(client.chat.completions.calls) >= 2
    followup_messages = client.chat.completions.calls[1]["messages"]
    _assert_tool_replies_contiguous(followup_messages)

    # Locate the parallel deepen turn: both tool replies, then both envelopes.
    deepen_idx = next(
        i
        for i, msg in enumerate(followup_messages)
        if getattr(msg, "tool_calls", None)
        and {tc.id for tc in msg.tool_calls} == {deepen_a.id, deepen_b.id}
    )
    after = followup_messages[deepen_idx + 1 : deepen_idx + 5]
    assert [m.get("role") for m in after] == ["tool", "tool", "user", "user"]
    assert {m.get("tool_call_id") for m in after[:2]} == {deepen_a.id, deepen_b.id}
