"""Tests for Reasoner tool result compaction."""
from __future__ import annotations

import json
import os

import pytest


def test_compact_tools_enabled_default():
    """Compact tools should be enabled by default."""
    from ai_agent.reasoner import _compact_tools_enabled

    # Default is ON
    assert _compact_tools_enabled()


def test_compact_tools_disabled_by_env():
    """Compact tools can be disabled via env var."""
    from ai_agent.reasoner import _compact_tools_enabled

    old_val = os.environ.get("RIFTBOUND_REASONER_COMPACT_TOOLS")
    try:
        os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "0"
        assert not _compact_tools_enabled()

        os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "false"
        assert not _compact_tools_enabled()

        os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "1"
        assert _compact_tools_enabled()
    finally:
        if old_val is None:
            os.environ.pop("RIFTBOUND_REASONER_COMPACT_TOOLS", None)
        else:
            os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = old_val


def test_compact_deepen_result_preserves_critical_fields():
    """Compact deepen preserves all fields needed for commit."""
    from ai_agent.reasoner import _compact_deepen_result

    full_result = {
        "_tool_name": "deepen",
        "source": "live_engine",
        "result_status": "novel",
        "seed_moves": ["play card-1", "activate card-1"],
        "extra_depth": 4,
        "prefix_steps": 2,
        "legal": True,
        "candidate_lines": [
            {
                "line_id": "deepen-1-0",
                "moves": ["play card-1", "activate card-1", "pass", "end turn", "play card-2"],
                "move_contexts": [{}, {}, {}, {}, {}],
                "expected_pre_hashes": ["hash1", "hash2", "hash3", "hash4", "hash5"],
                "score": 2.5,
                "risk_adjusted_score": 2.3,
                "risk_penalty": 0.2,
                "complete": True,
                "terminal_reason": "end_turn",
                "root_state_hash": "root_abc123",
                "resolved_state": {
                    "wins_game": False,
                    "my_score_after": 5,
                    "opp_score_after": 3,
                    "conquer": ["battlefield-1"],
                    "next_decision": "opponent_turn",
                },
            },
            {
                "line_id": "deepen-1-1",
                "moves": ["play card-1", "pass", "end turn"],
                "move_contexts": [{}, {}, {}],
                "expected_pre_hashes": ["hash1", "hash6", "hash7"],
                "score": 2.2,
                "complete": True,
                "terminal_reason": "end_turn",
                "root_state_hash": "root_abc123",
                "resolved_state": {"my_score_after": 4, "opp_score_after": 3},
            },
        ],
    }

    compact = _compact_deepen_result(full_result)

    # Critical metadata preserved
    assert compact["_tool_name"] == "deepen"
    assert compact["source"] == "live_engine"
    assert compact["result_status"] == "novel"
    assert compact["seed_moves"] == ["play card-1", "activate card-1"]
    assert compact["extra_depth"] == 4
    assert compact["prefix_steps"] == 2

    # Lines compacted but required fields present
    assert "candidate_lines" in compact
    assert len(compact["candidate_lines"]) == 2
    assert compact["line_count"] == 2
    assert compact["compacted"] is True

    line0 = compact["candidate_lines"][0]
    assert line0["line_id"] == "deepen-1-0"
    assert line0["root_state_hash"] == "root_abc123"
    assert line0["expected_pre_hashes"] == ["hash1", "hash2", "hash3", "hash4", "hash5"]
    assert line0["complete"] is True
    assert line0["terminal_reason"] == "end_turn"
    assert line0["score"] == 2.5
    assert line0["risk_adjusted_score"] == 2.3
    assert line0["risk_penalty"] == 0.2

    # Moves truncated to first 6
    assert len(line0["moves"]) <= 6

    # Resolved state compacted to key deltas
    assert "resolved_state" in line0
    assert "my_score_after" in line0["resolved_state"]
    assert "opp_score_after" in line0["resolved_state"]
    assert "conquer" not in line0["resolved_state"]  # Non-key field dropped


def test_compact_deepen_result_caps_line_count():
    """Compact deepen caps at top 10 lines."""
    from ai_agent.reasoner import _compact_deepen_result

    full_result = {
        "_tool_name": "deepen",
        "source": "live_engine",
        "candidate_lines": [
            {
                "line_id": f"line-{i}",
                "moves": ["play card-1"],
                "expected_pre_hashes": ["hash1"],
                "score": 1.0 + i * 0.1,
                "complete": True,
                "root_state_hash": "root",
            }
            for i in range(15)
        ],
    }

    compact = _compact_deepen_result(full_result)

    # Only top 10 lines kept
    assert len(compact["candidate_lines"]) == 10
    assert compact["line_count"] == 15


def test_compact_deepen_result_under_size_cap():
    """Compact deepen output stays under token size cap."""
    from ai_agent.reasoner import MAX_COMPACT_TOOL_SIZE, _compact_deepen_result, _estimate_tokens

    full_result = {
        "_tool_name": "deepen",
        "source": "live_engine",
        "result_status": "novel",
        "candidate_lines": [
            {
                "line_id": f"line-{i}",
                "moves": ["play card-1"] * 20,  # Long move list
                "expected_pre_hashes": [f"hash{j}" for j in range(20)],
                "score": 2.0,
                "complete": True,
                "root_state_hash": "root_hash",
                "resolved_state": {
                    "my_score_after": 5,
                    "opp_score_after": 3,
                    "cards_drawn": 10,
                    "energy_spent": 15,
                    "next_decision": "opponent_turn",
                },
            }
            for i in range(10)
        ],
    }

    compact = _compact_deepen_result(full_result)
    compact_json = json.dumps(compact)
    tokens = _estimate_tokens(compact_json)

    # Should be under the cap
    assert tokens < MAX_COMPACT_TOOL_SIZE * 1.5  # Allow some headroom for encoding


def test_create_tool_stub():
    """Tool stub contains expected metadata."""
    from ai_agent.reasoner import _create_tool_stub

    stub_json = _create_tool_stub("deepen", 52000, "result_status=novel")
    stub = json.loads(stub_json)

    assert stub["_stub"] is True
    assert stub["_tool_name"] == "deepen"
    assert stub["_original_tokens"] == 52000
    assert "Previous deepen result" in stub["note"]
    assert stub["summary"] == "result_status=novel"


def test_replace_old_tool_results_with_stubs():
    """Old tool results replaced with stubs, latest kept full."""
    from ai_agent.reasoner import _replace_old_tool_results_with_stubs

    old_val = os.environ.get("RIFTBOUND_REASONER_COMPACT_TOOLS")
    try:
        os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "1"

        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User message"},
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": json.dumps({
                    "_tool_name": "deepen",
                    "result_status": "duplicate",
                    "candidate_lines": [{"line_id": "line-1"}],
                }),
            },
            {"role": "assistant", "content": "Let me search more"},
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "content": json.dumps({
                    "_tool_name": "search_for",
                    "result_status": "empty",
                    "candidate_lines": [],
                }),
            },
            {"role": "assistant", "content": "Let me deepen again"},
            {
                "role": "tool",
                "tool_call_id": "call_3",
                "content": json.dumps({
                    "_tool_name": "deepen",
                    "result_status": "novel",
                    "candidate_lines": [{"line_id": "line-2"}],
                }),
            },
        ]

        modified = _replace_old_tool_results_with_stubs(messages)

        # System and user messages unchanged
        assert modified[0] == messages[0]
        assert modified[1] == messages[1]

        # First deepen replaced with stub
        first_deepen = json.loads(modified[2]["content"])
        assert first_deepen["_stub"] is True
        assert first_deepen["_tool_name"] == "deepen"
        assert "result_status=duplicate" in first_deepen["summary"]

        # search_for kept full (only occurrence)
        search_for = json.loads(modified[4]["content"])
        assert search_for.get("_stub") is not True
        assert search_for["_tool_name"] == "search_for"

        # Second deepen kept full (latest)
        second_deepen = json.loads(modified[6]["content"])
        assert second_deepen.get("_stub") is not True
        assert second_deepen["_tool_name"] == "deepen"
        assert second_deepen["result_status"] == "novel"

    finally:
        if old_val is None:
            os.environ.pop("RIFTBOUND_REASONER_COMPACT_TOOLS", None)
        else:
            os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = old_val


def test_replace_old_tool_results_disabled():
    """When compaction disabled, messages unchanged."""
    from ai_agent.reasoner import _replace_old_tool_results_with_stubs

    old_val = os.environ.get("RIFTBOUND_REASONER_COMPACT_TOOLS")
    try:
        os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = "0"

        messages = [
            {"role": "system", "content": "System prompt"},
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "content": json.dumps({"_tool_name": "deepen", "candidate_lines": []}),
            },
            {
                "role": "tool",
                "tool_call_id": "call_2",
                "content": json.dumps({"_tool_name": "deepen", "candidate_lines": []}),
            },
        ]

        modified = _replace_old_tool_results_with_stubs(messages)

        # Messages unchanged when disabled
        assert modified == messages

    finally:
        if old_val is None:
            os.environ.pop("RIFTBOUND_REASONER_COMPACT_TOOLS", None)
        else:
            os.environ["RIFTBOUND_REASONER_COMPACT_TOOLS"] = old_val


def test_compact_tool_result_other_tools():
    """Non-deepen search tools also get compacted."""
    from ai_agent.reasoner import _compact_tool_result

    result = {
        "_tool_name": "search_for",
        "candidate_lines": [{"line_id": f"line-{i}"} for i in range(10)],
    }

    compact = _compact_tool_result("search_for", result)

    assert len(compact["candidate_lines"]) == 5  # Cap at 5 for other tools
    assert compact["line_count"] == 10
    assert compact["compacted"] is True
