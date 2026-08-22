"""Unit tests for compact ANSI search-log formatters."""
from __future__ import annotations

from ai_agent.search_log_fmt import (
    RESET,
    format_breakdown_line,
    format_candidate_corpus,
    format_candidate_line,
    format_delta_line,
    format_line_header,
    format_risk_block,
    format_risk_line,
    format_stats_line,
    nonzero_items,
    summarize_risk_payload,
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


def test_nonzero_items_drops_zeros_and_false():
    items = dict(
        nonzero_items(
            {
                "a": 0,
                "b": 0.0,
                "c": 1e-12,
                "d": False,
                "e": True,
                "f": 1.5,
                "g": "x",
            }
        )
    )
    assert items == {"e": True, "f": 1.5, "g": "x"}


def test_format_stats_line_is_single_line():
    line = format_stats_line(
        {
            "mode": "main",
            "nodes_explored": 4,
            "branches_expanded": 7,
            "transposition_hits": 0,
            "max_depth_reached": 4,
            "beam_width": 8,
            "elapsed_ms": 19,
            "stopped_reason": "exhausted",
        }
    )
    plain = _strip_ansi(line)
    assert "\n" not in plain
    assert "mode=main" in plain
    assert "nodes=4" in plain
    assert "19ms" in plain
    assert "exhausted" in plain
    assert RESET in line  # colored


def test_format_breakdown_line_omits_zeros():
    line = format_breakdown_line(
        {
            "battlefield_conquered": 0.0,
            "unit_might_on_board": 3.3,
            "rune_development": -2.1,
            "cards_in_hand": -0.1,
            "idle_base_might": 1.5,
            "points_to_win": 8,
            "shaping_clamped": False,
            "total": 2.6,
        }
    )
    plain = _strip_ansi(line)
    assert "\n" not in plain
    assert "battlefield_conquered" not in plain
    assert "shaping_clamped" not in plain
    assert "unit_might_on_board" in plain
    assert "rune_development" in plain
    assert "points_to_win=8" in plain
    assert "points_to_win+" not in plain
    assert "total=" in plain


def test_format_delta_line_omits_false_zeros():
    line = format_delta_line(
        {
            "conquer": False,
            "my_score_after": 0,
            "opp_score_after": 0,
            "next_decision": "opponent's turn",
            "wins_game": False,
        }
    )
    plain = _strip_ansi(line)
    assert "\n" not in plain
    assert "next=opponent's turn" in plain
    assert "conquer" not in plain
    assert "wins_game" not in plain
    assert "my_score_after" not in plain


def test_format_delta_keeps_true_flags():
    plain = _strip_ansi(
        format_delta_line(
            {
                "conquer": True,
                "wins_game": True,
                "my_score_after": 2,
                "next_decision": "main",
            }
        )
    )
    assert "conquer=true" in plain
    assert "wins_game=true" in plain
    assert "my_score_after=2" in plain


def test_format_line_header_colored_score():
    plain = _strip_ansi(format_line_header("line-1", 2.6))
    assert plain == "line-1 | score=+2.600"
    assert RESET in format_line_header("line-1", 2.6)


def test_format_line_header_includes_cluster_when_collapsed():
    plain = _strip_ansi(
        format_line_header("line-1", 3.9, cluster_key="play falling-star-3", cluster_size=3)
    )
    assert "cluster=play falling-star-3" in plain
    assert "×3" in plain


def test_format_candidate_line_includes_moves_breakdown_and_delta():
    plain = "\n".join(
        _strip_ansi(line)
        for line in format_candidate_line(
            {
                "line_id": "scout-line-1",
                "score": 2.25,
                "moves": ["play scout-unit", "end turn"],
                "move_contexts": [
                    {"kind": "scripted", "context": "main"},
                    {"kind": "scripted"},
                ],
                "score_breakdown": {"unit_might_on_board": 2.25, "total": 2.25},
                "resolved_state": {"next_decision": "opponent's turn"},
            }
        )
    )
    assert "scout-line-1 | score=+2.250" in plain
    assert "play scout-unit" in plain
    assert "(main)" in plain
    assert "end turn" in plain
    assert "unit_might_on_board" in plain
    assert "next=opponent's turn" in plain


def test_format_candidate_corpus_prepends_stats_and_heading():
    plain = "\n".join(
        _strip_ansi(line)
        for line in format_candidate_corpus(
            [{"line_id": "scout-line-2", "score": 1.0, "moves": ["pass"]}],
            stats={"mode": "main", "nodes_explored": 4},
            heading="Scout lines (1):",
        )
    )
    assert "Scout lines (1):" in plain
    assert "mode=main" in plain
    assert "scout-line-2 | score=+1.000" in plain
    assert "pass" in plain


def test_format_risk_line_shows_summary_and_flags():
    plain = _strip_ansi(
        format_risk_line(
            {
                "risk_worst": 2.5,
                "risk_expected": 1.1,
                "can_recapture": True,
                "needs_recapture": True,
                "information_mode": "belief_hidden_state",
                "threats": [{"card_id": "defy"}],
            }
        )
    )
    assert "worst=+2.5" in plain
    assert "expected=+1.1" in plain
    assert "plan_broken" in plain
    assert "can_recapture" in plain
    assert "belief_hidden_state" in plain
    assert "(1 probed)" in plain


def test_format_risk_block_sorts_threats_by_delta():
    plain = "\n".join(_strip_ansi(line) for line in format_risk_block(
        {
            "risk_worst": 2.5,
            "risk_expected": 1.1,
            "needs_recapture": True,
            "threats": [
                {
                    "card_id": "gust",
                    "p_in_hand": 0.18,
                    "window_delta": 0.8,
                    "window_after_move": "pass",
                },
                {
                    "card_id": "defy",
                    "p_in_hand": 0.42,
                    "window_delta": 2.5,
                    "window_after_move": "play unit-x",
                    "plan_broken": True,
                    "broken_claims": ["conquer"],
                    "can_recapture": True,
                    "score_after_recapture": -0.5,
                },
            ],
        }
    ))
    defy_pos = plain.find("defy")
    gust_pos = plain.find("gust")
    assert defy_pos >= 0 and gust_pos >= 0
    assert defy_pos < gust_pos
    assert "p=42%" in plain
    assert "Δ=+2.5" in plain
    assert "@play unit-x" in plain
    assert "broken=[conquer]" in plain
    assert "after_recapture=-0.5" in plain


def test_format_candidate_line_includes_risk_block_and_header_hint():
    plain = "\n".join(
        _strip_ansi(line)
        for line in format_candidate_line(
            {
                "line_id": "line-3",
                "score": 3.0,
                "moves": ["play unit", "end turn"],
                "score_breakdown": {"total": 3.0},
                "resolved_state": {"next_decision": "opponent's turn"},
                "risk": {
                    "risk_worst": 1.2,
                    "risk_expected": 0.4,
                    "threats": [
                        {
                            "card_id": "defy",
                            "p_in_hand": 0.3,
                            "window_delta": 1.2,
                            "note": "threat_not_legal_in_any_window",
                        }
                    ],
                },
            }
        )
    )
    assert "line-3 | score=+3.000 | risk_worst=+1.2" in plain
    assert "Risk:" in plain
    assert "worst=+1.2" in plain
    assert "defy" in plain
    assert "threat_not_legal_in_any_window" in plain


def test_format_candidate_line_omits_risk_when_absent():
    plain = "\n".join(
        _strip_ansi(line)
        for line in format_candidate_line(
            {"line_id": "line-4", "score": 1.0, "moves": ["pass"]}
        )
    )
    assert "Risk:" not in plain
    assert "risk_worst" not in plain


def test_format_candidate_line_shows_clear_risk_when_probed_but_zero():
    plain = "\n".join(
        _strip_ansi(line)
        for line in format_candidate_line(
            {
                "line_id": "line-5",
                "score": 1.0,
                "moves": ["pass"],
                "risk": {
                    "risk_worst": 0.0,
                    "risk_expected": 0.0,
                    "threats": [],
                    "can_recapture": False,
                    "needs_recapture": False,
                },
            }
        )
    )
    assert "Risk:" in plain
    assert "clear" in plain


def test_format_risk_line_explains_skipped_illegal_threats():
    plain = _strip_ansi(
        format_risk_line(
            {
                "risk_worst": 0.0,
                "risk_expected": 0.0,
                "threats": [],
                "skipped": [
                    {"card_id": "defy", "reason": "no_legal_command"},
                    {"card_id": "discipline", "reason": "no_legal_command"},
                ],
            }
        )
    )
    assert "no legal assumed interrupt" in plain
    assert "defy/no_legal_command" in plain
    assert "discipline/no_legal_command" in plain


def test_format_candidate_line_marks_unprobed_contested_lines():
    plain = "\n".join(
        _strip_ansi(line)
        for line in format_candidate_line(
            {
                "line_id": "line-6",
                "score": 1.0,
                "moves": ["move unit to battlefield-a"],
                "opponent_windows": [{"after_move": "move unit to battlefield-a"}],
            }
        )
    )
    assert "Risk:" in plain
    assert "not probed" in plain


def test_summarize_risk_payload_for_reasoner_prompt():
    summary = summarize_risk_payload(
        {
            "risk_worst": 2.5,
            "risk_expected": 1.1,
            "needs_recapture": True,
            "can_recapture": True,
            "information_mode": "belief_hidden_state",
            "threats": [
                {
                    "card_id": "defy",
                    "p_in_hand": 0.42,
                    "window_delta": 2.5,
                    "window_after_move": "move unit to battlefield-a",
                    "plan_broken": True,
                    "broken_claims": ["conquer"],
                }
            ],
        }
    )
    assert summary["risk_worst"] == 2.5
    assert summary["needs_recapture"] is True
    assert summary["threats"][0]["card_id"] == "defy"
    assert summary["threats"][0]["broken_claims"] == ["conquer"]
