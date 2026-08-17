"""Unit tests for compact ANSI search-log formatters."""
from __future__ import annotations

from ai_agent.search_log_fmt import (
    RESET,
    format_breakdown_line,
    format_candidate_corpus,
    format_candidate_line,
    format_delta_line,
    format_line_header,
    format_stats_line,
    nonzero_items,
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
