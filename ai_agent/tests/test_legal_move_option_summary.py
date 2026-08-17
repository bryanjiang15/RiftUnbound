"""Tests for grouped legal-move parameter summaries in agent.py."""
from __future__ import annotations

from ai_agent.agent import _build_legal_move_option_lines, _format_brief_state


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


def test_format_brief_state_includes_legend_ability():
    text = _format_brief_state(
        {
            "turn_number": 9,
            "current_phase": "MAIN",
            "current_state": "NEUTRAL_OPEN",
            "decision_type": "main_phase",
            "my_score": 3,
            "opponent_score": 2,
            "my_energy": 0,
            "my_power": {},
            "my_runes": [],
            "my_hand": [],
            "my_legend": {
                "instance_id": "legend-p1",
                "name": "Kai'Sa - Daughter of the Void",
                "is_exhausted": False,
                "effect_text": "Exhaust: Reaction — Add a rainbow rune. Use only to play spells.",
                "abilities": [
                    {
                        "ability_id": "kaisa-add-spell-rainbow",
                        "ability_type": "activated",
                        "effect_type": "add_power",
                        "is_reaction": True,
                        "is_action": False,
                        "cost": "EXH",
                    }
                ],
            },
            "legal_moves": ["use legend-p1", "end turn"],
        }
    )
    assert "Legend: legend-p1" in text
    assert "Kai'Sa" in text
    assert "rainbow rune" in text
    assert "use legend-p1" in text
    assert "activated (Reaction)" in text
