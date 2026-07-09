from __future__ import annotations

from ai_agent import agent as ag
from ai_agent.goal_compiler import ProfileOverlay
from ai_agent.schemas import CandidateLine


def _line(line_id: str, score: float, *, moves, features=None, breakdown=None) -> CandidateLine:
    return CandidateLine(
        line_id=line_id,
        moves=moves,
        score=score,
        features=features or {},
        score_breakdown=breakdown or {},
    )


def test_argmax_without_overlay_picks_top_raw_score():
    lines = [
        _line("a", 10.0, moves=["play x to battlefield-a"]),
        _line("b", 5.0, moves=["play y to battlefield-b"]),
    ]
    dec = ag._argmax_line(lines, source="argmax")
    assert dec.chosen_line_id == "a"


def test_overlay_state_target_flips_selection():
    # Line "b" is worse on raw score but reaches the goal state (ready runes),
    # so the goal overlay should make it win the argmax.
    lines = [
        _line("a", 10.0, moves=["play x to battlefield-a"], features={"my_ready_runes": 0}),
        _line("b", 8.0, moves=["pass"], features={"my_ready_runes": 4}),
    ]
    overlay = ProfileOverlay(situational_terms=[{
        "id": "runes", "metric": "my_ready_runes", "metric_key": None,
        "comparator": ">=", "threshold": 4.0, "weight": 6.0,
    }])
    # b adjusted = 8 + 6*1.0 = 14 > a adjusted = 10 + 0 = 10
    dec = ag._argmax_line(lines, source="argmax", overlay=overlay)
    assert dec.chosen_line_id == "b"
    assert "Goal-argmax" in dec.reasoning


def test_overlay_weight_bias_uses_breakdown():
    lines = [
        _line("a", 10.0, moves=["play x"], breakdown={"enemy_unit_killed": 0.0}),
        _line("b", 9.0, moves=["play y"], breakdown={"enemy_unit_killed": 3.0}),
    ]
    overlay = ProfileOverlay(weight_multipliers={"action_weights.enemy_unit_killed": 2.0})
    # b adjusted = 9 + (2-1)*3 = 12 > a adjusted = 10
    dec = ag._argmax_line(lines, source="argmax", overlay=overlay)
    assert dec.chosen_line_id == "b"


def test_empty_overlay_is_inert():
    lines = [
        _line("a", 10.0, moves=["play x"]),
        _line("b", 5.0, moves=["play y"]),
    ]
    dec = ag._argmax_line(lines, source="argmax", overlay=ProfileOverlay())
    assert dec.chosen_line_id == "a"
    assert "Goal" not in dec.reasoning
