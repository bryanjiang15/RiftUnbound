from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from ai_agent import reasoner
from ai_agent.reasoner_context import ReasonerTurnContext, install_context, reset_context


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
        self.calls.append(kwargs)
        return _Response(self.messages.pop(0))


class _Client:
    def __init__(self, messages):
        self.chat = type("Chat", (), {"completions": _Completions(messages)})()


def _line(context: ReasonerTurnContext, moves: list[str], source: str = "scout") -> dict:
    line = context.registry.register(
        {
            "line_id": "line-1",
            "moves": moves,
            "move_contexts": [{"kind": "scripted"} for _ in moves],
            "expected_pre_hashes": ["root"] + [f"h{i}" for i in range(len(moves) - 1)],
            "root_state_hash": "root",
            "legal": True,
            "complete": True,
            "terminal_reason": "end_turn",
            "score": 3.93,
            "resolved_state": {"points_scored": 1, "hand_size": 4},
        },
        source=source,
    )
    assert line is not None
    return line


def test_duplicate_search_does_not_satisfy_novelty_gate():
    state = {"turn_number": 4, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g-dup", state, "root")
    scout = _line(context, ["pass", "end turn"])
    context.scout_lines = [scout, dict(scout, line_id="other")]
    client = _Client(
        [
            _Message(
                tool_calls=[
                    _ToolCall(
                        "deepen",
                        {"line_id": scout["line_id"], "prefix_steps": 1},
                    )
                ]
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "commit_line",
                        {
                            "line_id": scout["line_id"],
                            "rationale": "Compared with scout; duplicate only.",
                        },
                    )
                ]
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "search_for",
                        {
                            "constraints": [
                                {
                                    "metric": "points_scored",
                                    "comparator": ">=",
                                    "threshold": 1,
                                }
                            ]
                        },
                    )
                ]
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "commit_line",
                        {
                            "line_id": scout["line_id"],
                            "rationale": (
                                "Compared with scout; the alternative leaves more "
                                "ready runes and battlefield control."
                            ),
                        },
                    )
                ]
            ),
        ]
    )

    def fake_tool(trace, *, round_num, name, args):
        trace.append({"round": round_num, "name": name, "args": args, "summary": name})
        if name == "deepen":
            return json.dumps(
                {
                    "source": "live_engine",
                    "candidate_lines": [
                        {
                            "line_id": scout["line_id"],
                            "moves": list(scout["moves"]),
                            "complete": True,
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "source": "live_engine",
                "matches": [
                    {
                        "line_id": "alt",
                        "moves": ["end turn"],
                        "complete": True,
                        "resolved_state": {"points_scored": 0, "hand_size": 5},
                    }
                ],
            }
        )

    token = install_context(context)
    try:
        with patch("ai_agent.agent._invoke_traced_tool", side_effect=fake_tool):
            emit = asyncio.run(
                reasoner._request_reasoning(
                    client=client,
                    model="gpt-4o",
                    game_id="g-dup",
                    brief_state=state,
                    memory_summary="",
                    known_lines=context.scout_lines,
                    root_state_hash="root",
                )
            )
    finally:
        reset_context(token)

    assert emit.kind == "line"
    assert context.telemetry["local_fork_attempted"] is True
    assert context.telemetry["novel_investigation"] is True
    assert context.telemetry["investigation_satisfied"] is True
    assert any("duplicate" in str(err).lower() or "novel" in str(err).lower()
               for err in context.telemetry.get("terminal_validation_errors", []))


def test_score_only_rationale_rejected_when_comparison_required():
    state = {"turn_number": 5, "legal_moves": ["pass", "end turn"]}
    context = ReasonerTurnContext("g-score", state, "root")
    scout = _line(context, ["pass", "end turn"])
    alt = context.registry.register(
        {
            "line_id": "alt",
            "moves": ["end turn"],
            "move_contexts": [{"kind": "scripted"}],
            "expected_pre_hashes": ["root"],
            "root_state_hash": "root",
            "legal": True,
            "complete": True,
            "terminal_reason": "end_turn",
            "score": 3.83,
            "resolved_state": {"points_scored": 0, "hand_size": 5},
        },
        source="deepen-1",
    )
    context.scout_lines = [scout]
    client = _Client(
        [
            _Message(
                tool_calls=[
                    _ToolCall(
                        "search_for",
                        {
                            "constraints": [
                                {
                                    "metric": "points_scored",
                                    "comparator": ">=",
                                    "threshold": 0,
                                }
                            ]
                        },
                    )
                ]
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "commit_line",
                        {
                            "line_id": scout["line_id"],
                            "rationale": "3.93 is higher than 3.83 so commit scout.",
                        },
                    )
                ]
            ),
            _Message(
                tool_calls=[
                    _ToolCall(
                        "commit_line",
                        {
                            "line_id": scout["line_id"],
                            "rationale": (
                                "Compared with scout; keep scout for battlefield "
                                "control despite a tiny score gap."
                            ),
                        },
                    )
                ]
            ),
        ]
    )

    def fake_tool(trace, *, round_num, name, args):
        trace.append({"round": round_num, "name": name, "args": args, "summary": "ok"})
        return json.dumps(
            {
                "source": "live_engine",
                "matches": [alt],
            }
        )

    token = install_context(context)
    try:
        with patch("ai_agent.agent._invoke_traced_tool", side_effect=fake_tool):
            emit = asyncio.run(
                reasoner._request_reasoning(
                    client=client,
                    model="gpt-4o",
                    game_id="g-score",
                    brief_state=state,
                    memory_summary="",
                    known_lines=context.scout_lines,
                    root_state_hash="root",
                )
            )
    finally:
        reset_context(token)

    assert emit.kind == "line"
    assert any(
        "score-only" in str(err).lower()
        for err in context.telemetry.get("terminal_validation_errors", [])
    )


def test_scout_render_includes_resolved_state_and_score_band():
    rendered = reasoner._render_scout_lines(
        [
            {
                "line_id": "scout-1",
                "moves": ["play a", "choose x", "end turn"],
                "move_contexts": [
                    {"kind": "scripted"},
                    {"kind": "auto_choice"},
                    {"kind": "scripted"},
                ],
                "score": 3.93,
                "score_breakdown": {"points": 2.0},
                "resolved_state": {"runes_recycled": 1, "my_score_after": 3},
                "complete": True,
                "opponent_windows": [],
                "root_state_hash": "root",
            }
        ]
    )
    assert rendered[0]["resolved_state"]["runes_recycled"] == 1
    assert "score_band" in rendered[0]
    assert "score" not in rendered[0]  # hidden by default
    assert rendered[0]["strategic_prefix_moves"] == ["play a"]
    assert rendered[0]["cluster_size"] == 1
    assert rendered[0]["deepen_hint"]["cluster_prefix_steps"] == 1


def test_scout_render_includes_cluster_metadata():
    rendered = reasoner._render_scout_lines(
        [
            {
                "line_id": "scout-1",
                "moves": ["play falling-star-3 target a", "end turn"],
                "move_contexts": [{"kind": "scripted"}, {"kind": "scripted"}],
                "score": 3.9,
                "score_breakdown": {},
                "resolved_state": {},
                "complete": True,
                "opponent_windows": [],
                "root_state_hash": "root",
                "cluster_key": "play falling-star-3",
                "cluster_size": 3,
                "cluster_prefix_steps": 1,
            }
        ]
    )
    assert rendered[0]["cluster_key"] == "play falling-star-3"
    assert rendered[0]["cluster_size"] == 3
    assert rendered[0]["deepen_hint"]["cluster_prefix_steps"] == 1
