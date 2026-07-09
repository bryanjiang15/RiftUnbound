from __future__ import annotations

import math

import pytest

from ai_agent import goal_compiler as gc
from ai_agent.schemas import Goal, GoalSet


# ── Helpers ──────────────────────────────────────────────────────────────────


def _gs(*goals: Goal) -> GoalSet:
    return GoalSet(turn=3, rationale="t", goals=list(goals))


# A registry map independent of the on-disk manifest, so tests are hermetic.
@pytest.fixture(autouse=True)
def _fixed_registry(monkeypatch):
    fake = {
        "battlefield_control": "state_weights",
        "reactive_potential": "state_weights",
        "enemy_unit_killed": "action_weights",
        "card_played": "action_weights",
    }
    monkeypatch.setattr(gc, "weight_bias_features", lambda path=None: dict(fake))
    return fake


# ── weight_bias ──────────────────────────────────────────────────────────────


def test_weight_bias_uses_priority_when_multiplier_omitted():
    overlay = gc.compile_goals(_gs(Goal(id="g1", kind="weight_bias", feature="battlefield_control", priority="high")))
    assert overlay.weight_multipliers == {"state_weights.battlefield_control": gc.PRIORITY_MULTIPLIER["high"]}


def test_weight_bias_clamps_multiplier():
    overlay = gc.compile_goals(_gs(Goal(id="g1", kind="weight_bias", feature="card_played", multiplier=99.0)))
    assert overlay.weight_multipliers["action_weights.card_played"] == gc.MULTIPLIER_MAX
    overlay = gc.compile_goals(_gs(Goal(id="g2", kind="weight_bias", feature="card_played", multiplier=0.01)))
    assert overlay.weight_multipliers["action_weights.card_played"] == gc.MULTIPLIER_MIN


def test_weight_bias_unknown_feature_is_noop():
    overlay = gc.compile_goals(_gs(Goal(id="g1", kind="weight_bias", feature="not_a_feature", multiplier=2.0)))
    assert overlay.weight_multipliers == {}
    assert any("not a registry weight" in n for n in overlay.notes)


def test_duplicate_ids_dropped():
    overlay = gc.compile_goals(_gs(
        Goal(id="dup", kind="weight_bias", feature="card_played", multiplier=2.0),
        Goal(id="dup", kind="weight_bias", feature="enemy_unit_killed", multiplier=2.0),
    ))
    assert len(overlay.weight_multipliers) == 1
    assert any("duplicate id" in n for n in overlay.notes)


# ── state_target ─────────────────────────────────────────────────────────────


def test_state_target_scalar_compiles_with_priority_weight():
    overlay = gc.compile_goals(_gs(Goal(
        id="runes", kind="state_target", metric="my_ready_runes",
        comparator=">=", threshold=3, priority="med",
    )))
    assert len(overlay.situational_terms) == 1
    term = overlay.situational_terms[0]
    assert term["metric"] == "my_ready_runes"
    assert term["weight"] == gc.PRIORITY_BONUS_WEIGHT["med"]


def test_state_target_dict_metric_requires_key():
    overlay = gc.compile_goals(_gs(Goal(
        id="bf", kind="state_target", metric="bf_control_net",
        comparator=">=", threshold=1,
    )))
    assert overlay.situational_terms == []
    assert any("needs a metric_key" in n for n in overlay.notes)

    overlay = gc.compile_goals(_gs(Goal(
        id="bf", kind="state_target", metric="bf_control_net", metric_key="battlefield-b",
        comparator=">=", threshold=1,
    )))
    assert overlay.situational_terms[0]["metric_key"] == "battlefield-b"


def test_state_target_unknown_metric_noop():
    overlay = gc.compile_goals(_gs(Goal(
        id="x", kind="state_target", metric="bogus", comparator=">=", threshold=1,
    )))
    assert overlay.situational_terms == []


def test_state_target_missing_comparator_noop():
    overlay = gc.compile_goals(_gs(Goal(id="x", kind="state_target", metric="my_score", threshold=8)))
    assert overlay.situational_terms == []


# ── card_target ──────────────────────────────────────────────────────────────


def test_card_target_compiles():
    overlay = gc.compile_goals(_gs(Goal(id="c", kind="card_target", card_id="noxus-hopeful", priority="high")))
    assert overlay.card_bonuses == [{"id": "c", "card_id": "noxus-hopeful", "weight": gc.PRIORITY_BONUS_WEIGHT["high"]}]


def test_card_target_without_id_noop():
    overlay = gc.compile_goals(_gs(Goal(id="c", kind="card_target")))
    assert overlay.card_bonuses == []


# ── graded_value ─────────────────────────────────────────────────────────────


def test_graded_value_ge_ramps_then_caps():
    assert gc.graded_value(0, ">=", 4) == 0.0
    assert gc.graded_value(2, ">=", 4) == pytest.approx(0.5)
    assert gc.graded_value(4, ">=", 4) == 1.0
    assert gc.graded_value(9, ">=", 4) == 1.0  # capped


def test_graded_value_le_and_eq():
    assert gc.graded_value(3, "<=", 3) == 1.0          # at/under target
    assert gc.graded_value(0, "<=", 3) == 1.0
    assert gc.graded_value(3, "==", 3) == 1.0
    assert gc.graded_value(3, "==", 0) < 1.0           # off-target decays


# ── empty / robustness ───────────────────────────────────────────────────────


def test_empty_goalset_is_empty_overlay():
    assert gc.compile_goals(None).is_empty()
    assert gc.compile_goals(_gs()).is_empty()


# ── overlay_delta (server-side re-rank) ──────────────────────────────────────


def test_overlay_delta_weight_bias_exact_from_breakdown():
    overlay = gc.ProfileOverlay(weight_multipliers={"action_weights.enemy_unit_killed": 2.0})
    # term = weight·feature already captured in breakdown; ×2 ⇒ +1× the term.
    delta = gc.overlay_delta(overlay, features={}, score_breakdown={"enemy_unit_killed": 3.0}, moves=[])
    assert delta == pytest.approx(3.0)


def test_overlay_delta_state_target_graded():
    overlay = gc.ProfileOverlay(situational_terms=[{
        "id": "runes", "metric": "my_ready_runes", "metric_key": None,
        "comparator": ">=", "threshold": 4.0, "weight": 6.0,
    }])
    delta = gc.overlay_delta(overlay, features={"my_ready_runes": 2}, score_breakdown={}, moves=[])
    assert delta == pytest.approx(3.0)  # 6.0 · 0.5


def test_overlay_delta_dict_metric_and_absent_key():
    overlay = gc.ProfileOverlay(situational_terms=[{
        "id": "bf", "metric": "bf_might_margin", "metric_key": "battlefield-a",
        "comparator": ">=", "threshold": 8.0, "weight": 3.0,
    }])
    feats = {"bf_might_margin": {"battlefield-a": 4}}
    assert gc.overlay_delta(overlay, features=feats, score_breakdown={}, moves=[]) == pytest.approx(1.5)
    # absent battlefield key = neutral 0, not a crash
    assert gc.overlay_delta(overlay, features={"bf_might_margin": {}}, score_breakdown={}, moves=[]) == 0.0


def test_overlay_delta_card_bonus_matches_move_string():
    overlay = gc.ProfileOverlay(card_bonuses=[{"id": "c", "card_id": "noxus-hopeful", "weight": 6.0}])
    assert gc.overlay_delta(overlay, features={}, score_breakdown={}, moves=["play noxus-hopeful to battlefield-a"]) == 6.0
    assert gc.overlay_delta(overlay, features={}, score_breakdown={}, moves=["play other"]) == 0.0


def test_overlay_delta_breakdown_sums_to_delta_and_keys_by_id():
    overlay = gc.ProfileOverlay(
        weight_multipliers={"action_weights.enemy_unit_killed": 2.0},
        situational_terms=[{
            "id": "runes", "metric": "my_ready_runes", "metric_key": None,
            "comparator": ">=", "threshold": 4.0, "weight": 6.0,
        }],
        card_bonuses=[{"id": "play_x", "card_id": "noxus-hopeful", "weight": 3.0}],
    )
    feats = {"my_ready_runes": 2}
    bd = {"enemy_unit_killed": 3.0}
    moves = ["play noxus-hopeful"]
    parts = gc.overlay_delta_breakdown(overlay, features=feats, score_breakdown=bd, moves=moves)
    assert parts == {"enemy_unit_killed": 3.0, "runes": 3.0, "play_x": 3.0}
    total = gc.overlay_delta(overlay, features=feats, score_breakdown=bd, moves=moves)
    assert abs(sum(parts.values()) - total) < 1e-9
