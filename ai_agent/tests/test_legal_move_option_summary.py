"""Tests for grouped legal-move parameter summaries in agent.py."""
from __future__ import annotations

from ai_agent.agent import _build_legal_move_option_lines


def test_groups_destinations_for_same_play_move():
    legal = [
        "play noxus-hopeful",
        "play noxus-hopeful to battlefield-a",
        "play noxus-hopeful to battlefield-b",
        "play noxus-hopeful accelerate",
    ]

    lines = _build_legal_move_option_lines(legal)

    assert (
        "    play noxus-hopeful [to: base|battlefield-a|battlefield-b; flags: accelerate]"
        in lines
    )


def test_groups_targets_for_use_ability():
    legal = [
        "use annie-1",
        "use annie-1 target enemy-a",
        "use annie-1 target enemy-b",
    ]

    lines = _build_legal_move_option_lines(legal)

    assert "    use annie-1 [target: enemy-a|enemy-b]" in lines


def test_one_line_per_move_and_terminals_last():
    legal = [
        "end turn",
        "play noxus-hopeful",
        "play noxus-hopeful to battlefield-a",
        "move ranger to battlefield-a",
        "move ranger to battlefield-b",
        "pass",
    ]

    lines = _build_legal_move_option_lines(legal)

    # One line per distinct card/unit move (2 actions) + 2 terminals.
    assert lines == [
        "    play noxus-hopeful [to: base|battlefield-a]",
        "    move ranger [to: battlefield-a|battlefield-b]",
        "    end turn",
        "    pass",
    ]
