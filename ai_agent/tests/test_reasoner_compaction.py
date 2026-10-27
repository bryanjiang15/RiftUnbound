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
    """Compact deepen preserves fields needed for prompt, drops expected_pre_hashes."""
    from ai_agent.reasoner import _compact_deepen_result

    full_result = {
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

    # Critical metadata preserved (no _tool_name injection)
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
    # expected_pre_hashes dropped - commit reads from registry, not prompt
    assert "expected_pre_hashes" not in line0
    assert line0["complete"] is True
    assert line0["terminal_reason"] == "end_turn"
    # Score hidden by default (RIFTBOUND_REASONER_HIDE_RAW_SCORE=1)
    # but this test doesn't set env, so rely on hide_scores logic in compactor
    assert line0["risk_adjusted_score"] == 2.3
    assert line0["risk_penalty"] == 0.2

    # Moves truncated to first 6
    assert len(line0["moves"]) == 6  # Should be exactly 6 or less
    assert line0["moves"][0] == "play card-1"

    # Resolved state compacted to key deltas
    assert "resolved_state" in line0
    assert "my_score_after" in line0["resolved_state"]
    assert "opp_score_after" in line0["resolved_state"]
    assert "conquer" not in line0["resolved_state"]  # Non-key field dropped


def test_compact_deepen_result_caps_line_count():
    """Compact deepen caps at top 10 lines."""
    from ai_agent.reasoner import _compact_deepen_result

    full_result = {
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


def test_compact_deepen_result_enforces_size_cap():
    """Compact deepen output strictly enforced under MAX_COMPACT_TOOL_SIZE."""
    from ai_agent.reasoner import MAX_COMPACT_TOOL_SIZE, _compact_deepen_result, _estimate_tokens

    full_result = {
        "source": "live_engine",
        "result_status": "novel",
        "candidate_lines": [
            {
                "line_id": f"line-{i}",
                "moves": ["play card-1"] * 20,  # Long move list
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

    # Should be under the cap (no 1.5x allowance)
    assert tokens <= MAX_COMPACT_TOOL_SIZE, f"Expected <={MAX_COMPACT_TOOL_SIZE}, got {tokens}"


def test_classification_uses_full_moves_not_compacted():
    """Classification logic sees full moves, not the 6-move-truncated compact form."""
    from ai_agent.investigation_metrics import classify_search_result, move_tuple

    scout_leader = ("play card-1", "activate card-1", "pass", "end turn", "play card-2",
                    "play card-3", "play card-4", "end turn")
    
    # A deepen result with a line that matches scout_leader exactly
    result = {
        "source": "live_engine",
        "candidate_lines": [
            {
                "line_id": "deepen-1",
                "moves": list(scout_leader),  # 8 moves, same as scout
                "expected_pre_hashes": ["h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8"],
                "score": 2.5,
                "complete": True,
            }
        ],
    }

    # Classification on the FULL result should see it as duplicate
    status = classify_search_result("deepen", result, scout_leader)
    assert status == "duplicate", "Scout-duplicate line must be classified as duplicate"

    # Verify the line tuple matches
    lines = result["candidate_lines"]
    assert move_tuple(lines[0]) == scout_leader


def test_opponent_windows_from_raw_result():
    """Feedback envelope reads opponent_windows from raw result, not compacted."""
    from ai_agent.investigation_metrics import extract_result_lines

    # A result with opponent_windows on each line
    result = {
        "source": "live_engine",
        "candidate_lines": [
            {
                "line_id": "line-1",
                "moves": ["play card-1", "end turn"],
                "opponent_windows": [
                    {"command": "counter-1", "turn": 1},
                    {"command": "counter-2", "turn": 1},
                ],
                "complete": True,
            },
            {
                "line_id": "line-2",
                "moves": ["play card-2", "end turn"],
                "opponent_windows": [
                    {"command": "counter-3", "turn": 1},
                ],
                "complete": True,
            },
        ],
    }

    lines = extract_result_lines("deepen", result)
    total_windows = sum(len(line.get("opponent_windows", []) or []) for line in lines)
    
    # Should count all 3 opponent windows
    assert total_windows == 3, "Envelope should report 3 opponent windows from raw result"

