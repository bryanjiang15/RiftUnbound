"""Tests for the token/param-aware legal-move validation in agent.py.

These cover the core behavior change: a targeted spell/reaction whose only
enumerated legal move is the bare ``play <id>`` / ``react <id>`` form should be
accepted when the model adds an inline ``target <id>`` for a visible instance,
while malformed or out-of-state commands are still rejected.
"""
from __future__ import annotations

from ai_agent.agent import _command_in_legal_moves, _parse_command


# A minimal brief state listing the instance ids the seat can see.
BRIEF_STATE = {
    "my_hand": [{"instance_id": "burst-of-flame"}, {"instance_id": "flame-chompers"}],
    "my_base_units": [{"instance_id": "ranger"}],
    "opponent_base_units": [{"instance_id": "enemy-grunt"}],
    "my_champion": {"instance_id": "champ"},
    "battlefields": [
        {
            "battlefield_id": "battlefield-a",
            "my_units": [{"instance_id": "scout"}],
            "opponent_units": [{"instance_id": "enemy-brute"}],
            "my_facedown": {"instance_id": "hidden-trap"},
        }
    ],
}


# ── Exact + base-destination matches ─────────────────────────────────────────


def test_exact_match():
    assert _command_in_legal_moves("end turn", ["end turn", "pass"], BRIEF_STATE)


def test_play_to_base_matches_bare_play():
    legal = ["play flame-chompers", "end turn"]
    assert _command_in_legal_moves("play flame-chompers to base", legal, BRIEF_STATE)


# ── Targeted spell: the core fix ─────────────────────────────────────────────


def test_targeted_spell_accepted_when_bare_play_is_legal():
    # Engine enumerates only the untargeted form; the inline target names a
    # visible opponent unit, so the command must be accepted.
    legal = ["play burst-of-flame", "end turn"]
    assert _command_in_legal_moves(
        "play burst-of-flame target enemy-grunt", legal, BRIEF_STATE
    )


def test_targeted_spell_target_on_battlefield_unit():
    legal = ["play burst-of-flame"]
    assert _command_in_legal_moves(
        "play burst-of-flame target enemy-brute", legal, BRIEF_STATE
    )


def test_targeted_spell_rejected_for_unknown_target():
    legal = ["play burst-of-flame"]
    assert not _command_in_legal_moves(
        "play burst-of-flame target ghost-unit", legal, BRIEF_STATE
    )


def test_targeted_reaction_accepted():
    legal = ["react burst-of-flame", "pass"]
    assert _command_in_legal_moves(
        "react burst-of-flame target enemy-grunt", legal, BRIEF_STATE
    )


def test_lenient_when_no_state_available():
    # With no brief state we cannot validate the id, so fall back to accepting
    # any structurally-valid inline target rather than blocking the play.
    legal = ["play burst-of-flame"]
    assert _command_in_legal_moves(
        "play burst-of-flame target enemy-grunt", legal, None
    )


# ── Things that must still be rejected ───────────────────────────────────────


def test_wrong_card_id_rejected():
    legal = ["play burst-of-flame"]
    assert not _command_in_legal_moves(
        "play flame-chompers target enemy-grunt", legal, BRIEF_STATE
    )


def test_accelerate_flag_must_be_enumerated():
    legal = ["play flame-chompers"]
    assert not _command_in_legal_moves(
        "play flame-chompers accelerate", legal, BRIEF_STATE
    )


def test_accelerate_flag_matches_when_enumerated():
    legal = ["play flame-chompers", "play flame-chompers accelerate"]
    assert _command_in_legal_moves(
        "play flame-chompers accelerate", legal, BRIEF_STATE
    )


def test_move_destination_must_match():
    legal = ["move ranger to battlefield-a"]
    assert _command_in_legal_moves("move ranger to battlefield-a", legal, BRIEF_STATE)
    assert not _command_in_legal_moves(
        "move ranger to battlefield-b", legal, BRIEF_STATE
    )


def test_use_ability_exact_target_match():
    legal = ["use scout", "use scout target enemy-grunt"]
    assert _command_in_legal_moves("use scout target enemy-grunt", legal, BRIEF_STATE)


def test_unknown_trailing_token_rejected():
    legal = ["play flame-chompers"]
    assert not _command_in_legal_moves(
        "play flame-chompers bogus", legal, BRIEF_STATE
    )


def test_dangling_keyword_rejected():
    legal = ["play burst-of-flame"]
    assert not _command_in_legal_moves("play burst-of-flame target", legal, BRIEF_STATE)


# ── Parser unit checks ───────────────────────────────────────────────────────


def test_parse_command_structure():
    parsed = _parse_command("play burst-of-flame to battlefield-a target enemy-grunt accelerate")
    assert parsed["verb"] == "play"
    assert parsed["head"] == ("burst-of-flame",)
    assert parsed["to"] == "battlefield-a"
    assert parsed["target"] == "enemy-grunt"
    assert parsed["flags"] == {"accelerate"}


def test_parse_multi_unit_move():
    parsed = _parse_command("move ranger scout to battlefield-a")
    assert parsed["verb"] == "move"
    assert parsed["head"] == ("ranger", "scout")
    assert parsed["to"] == "battlefield-a"
