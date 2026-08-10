from __future__ import annotations

from ai_agent.investigation_metrics import (
    classify_search_result,
    has_novel_suffix,
    is_novel_vs_scout,
    metrics_from_reasoner_telemetry,
    rationale_is_score_primary,
    suggest_last_valid_prefix,
    summarize_investigation_trials,
)


def test_classify_duplicate_and_illegal_seed():
    scout = ("play a", "end turn")
    assert (
        classify_search_result(
            "deepen",
            {
                "source": "live_engine",
                "candidate_lines": [{"moves": list(scout), "complete": True}],
            },
            scout,
        )
        == "duplicate"
    )
    assert (
        classify_search_result(
            "deepen",
            {
                "source": "live_engine",
                "legal": False,
                "error": "seed move illegal: choose x",
                "stopped_reason": "seed_failed",
                "candidate_lines": [],
            },
            scout,
        )
        == "illegal_seed"
    )


def test_novel_vs_scout_and_suffix():
    scout = ("play a", "move a to battlefield-a", "end turn")
    result = {
        "source": "live_engine",
        "candidate_lines": [
            {
                "moves": ["play a", "move a to battlefield-b", "end turn"],
                "complete": True,
            }
        ],
    }
    assert is_novel_vs_scout("deepen", result, scout)
    assert has_novel_suffix("deepen", result, scout, prefix_len=1)


def test_score_primary_detector():
    assert rationale_is_score_primary("3.93 is higher than 3.83 so commit scout")
    assert not rationale_is_score_primary(
        "3.93 vs 3.83 is a tie; keep the line with more ready runes and battlefield control"
    )


def test_metrics_from_reasoner_telemetry_flattens_investigation_fields():
    metrics = metrics_from_reasoner_telemetry(
        {"kind": "line", "rationale": "Compared with scout; keep flexibility."},
        {"complete": True, "moves": ["pass"]},
        {
            "scout_agreement": True,
            "investigation_satisfied": True,
            "novel_investigation": True,
            "local_fork_attempted": True,
            "unique_sequence_count": 2,
            "selected_source_lineage": ["scout", "deepen-1"],
            "tool_mix": ["deepen", "commit_line"],
            "budget": {"time_remaining_ms": 1200},
            "failed_search_calls": 1,
            "recovered_failed_searches": 1,
            "model_calls": 3,
        },
    )
    assert metrics["scout_agreement"] is True
    assert metrics["novel_investigation"] is True
    assert metrics["local_fork_attempted"] is True
    assert metrics["unique_sequence_count"] == 2
    assert metrics["budget_remaining_ms"] == 1200
    assert metrics["failed_search_calls"] == 1


def test_summarize_investigation_trials_rates():
    summary = summarize_investigation_trials(
        [
            {
                "investigation_exemption": "forced",
                "scout_agreement": True,
                "committed": True,
                "chosen_line_complete": True,
                "reasoner_kind": "line",
            },
            {
                "investigation_exemption": None,
                "novel_investigation": True,
                "local_fork_attempted": True,
                "novel_suffix_found": True,
                "investigation_satisfied": True,
                "failed_search_calls": 1,
                "recovered_failed_searches": 1,
                "score_primary_rationale": False,
                "scout_agreement": False,
                "committed": True,
                "chosen_line_complete": True,
                "reasoner_kind": "line",
            },
        ]
    )
    assert summary["eligible_turns"] == 1
    assert summary["novel_investigation_rate"] == 1.0
    assert summary["local_fork_rate"] == 1.0
    assert summary["failed_query_recovery_rate"] == 1.0
    assert suggest_last_valid_prefix(["play a", "choose x"]) == ["play a"]
