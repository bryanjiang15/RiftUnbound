from __future__ import annotations

import pytest

from ai_agent import search_metrics as sm
from ai_agent import skills


# ── Fixtures: two hand-built candidate lines with concrete post-line states ────


def _line1() -> dict:
    return {
        "line_id": "line-1",
        "moves": ["move vi-1 to battlefield-b", "play gust-1", "end turn"],
        "score": 12.0,
        "search_state": {
            "units": {
                "vi-1": {"owner": "me", "might": 5, "damage": 1, "health": 4, "battlefield": "battlefield-b"},
                "jinx-1": {"owner": "opponent", "might": 3, "damage": 0, "health": 3, "battlefield": "battlefield-a"},
            },
            "battlefields": {
                "battlefield-a": {"my_might": 0, "opp_might": 3, "my_units": 0, "opp_units": 1, "controller": "opponent", "i_control": False},
                "battlefield-b": {"my_might": 5, "opp_might": 0, "my_units": 1, "opp_units": 0, "controller": "me", "i_control": True},
            },
            "players": {
                "me": {"score": 3, "cards_in_hand": 4, "ready_runes": 1},
                "opponent": {"score": 2, "cards_in_hand": 5, "ready_runes": 2},
            },
            "turn": {"points_scored": 1, "enemy_units_killed": 0, "battlefields_conquered": 1},
            "cards_played": ["gust-1"],
        },
    }


def _line2() -> dict:
    # vi-1 died; battlefield-b lost; opponent hand emptied down to 2.
    return {
        "line_id": "line-2",
        "moves": ["play nuke-1 target vi-1", "end turn"],
        "score": 8.0,
        "search_state": {
            "units": {
                "jinx-1": {"owner": "opponent", "might": 3, "damage": 0, "health": 3, "battlefield": "battlefield-b"},
            },
            "battlefields": {
                "battlefield-a": {"my_might": 0, "opp_might": 0, "my_units": 0, "opp_units": 0, "controller": None, "i_control": False},
                "battlefield-b": {"my_might": 2, "opp_might": 4, "my_units": 1, "opp_units": 1, "controller": "opponent", "i_control": False},
            },
            "players": {
                "me": {"score": 5, "cards_in_hand": 3, "ready_runes": 0},
                "opponent": {"score": 2, "cards_in_hand": 2, "ready_runes": 1},
            },
            "turn": {"points_scored": 3, "enemy_units_killed": 1, "battlefields_conquered": 0},
            "cards_played": ["nuke-1"],
        },
    }


def _corpus() -> list[dict]:
    return [_line1(), _line2()]


# ── Per-subject resolution ────────────────────────────────────────────────────


def test_unit_metrics_resolve():
    st = _line1()["search_state"]
    assert sm.evaluate_clause({"metric": "unit_might", "comparator": ">=", "threshold": 4, "target": "vi-1"}, st)["met"] is True
    assert sm.evaluate_clause({"metric": "unit_health", "comparator": ">=", "threshold": 4, "target": "vi-1"}, st)["value"] == 4.0
    assert sm.evaluate_clause({"metric": "unit_damage", "comparator": "<=", "threshold": 0, "target": "vi-1"}, st)["met"] is False
    assert sm.evaluate_clause({"metric": "unit_alive", "comparator": "==", "threshold": 1, "target": "vi-1"}, st)["met"] is True


def test_dead_unit_is_absent():
    st = _line2()["search_state"]  # vi-1 not present
    alive = sm.evaluate_clause({"metric": "unit_alive", "comparator": "==", "threshold": 1, "target": "vi-1"}, st)
    assert alive["supported"] is True and alive["value"] == 0.0 and alive["met"] is False
    might = sm.evaluate_clause({"metric": "unit_might", "comparator": ">=", "threshold": 1, "target": "vi-1"}, st)
    assert might["supported"] is True and might["value"] == 0.0


def test_battlefield_and_player_and_turn_and_card():
    st = _line1()["search_state"]
    assert sm.evaluate_clause({"metric": "i_control_battlefield", "comparator": "==", "threshold": 1, "target": "battlefield-b"}, st)["met"] is True
    assert sm.evaluate_clause({"metric": "my_might_on_battlefield", "comparator": ">=", "threshold": 5, "target": "battlefield-b"}, st)["met"] is True
    assert sm.evaluate_clause({"metric": "cards_in_hand", "comparator": "<=", "threshold": 2, "target": "opponent"}, st)["met"] is False
    assert sm.evaluate_clause({"metric": "battlefields_conquered", "comparator": ">=", "threshold": 1}, st)["met"] is True
    assert sm.evaluate_clause({"metric": "card_played", "comparator": "==", "threshold": 1, "target": "gust-1"}, st)["met"] is True
    assert sm.evaluate_clause({"metric": "card_played", "comparator": "==", "threshold": 1, "target": "never-1"}, st)["value"] == 0.0


def test_player_target_aliases():
    st = _line1()["search_state"]
    for alias in ("opponent", "opp", "enemy", "them"):
        r = sm.evaluate_clause({"metric": "cards_in_hand", "comparator": ">=", "threshold": 5, "target": alias}, st)
        assert r["supported"] and r["value"] == 5.0


# ── Graded vs boolean ─────────────────────────────────────────────────────────


def test_continuous_metric_is_graded():
    st = _line1()["search_state"]  # opponent hand = 5
    # want <= 3: value 5 is above the cap, partial credit but not met.
    r = sm.evaluate_clause({"metric": "cards_in_hand", "comparator": "<=", "threshold": 3, "target": "opponent"}, st)
    assert r["met"] is False
    assert 0.0 <= r["satisfaction"] < 1.0


def test_toward_threshold_scores_partial():
    st = _line1()["search_state"]  # vi-1 might = 5
    # want >= 10: halfway there → ~0.5.
    r = sm.evaluate_clause({"metric": "unit_might", "comparator": ">=", "threshold": 10, "target": "vi-1"}, st)
    assert r["satisfaction"] == pytest.approx(0.5, abs=0.01)


# ── Unsupported clauses (feedback, never crash) ───────────────────────────────


def test_unknown_metric_is_unsupported():
    r = sm.evaluate_clause({"metric": "keep_vi_happy", "comparator": ">=", "threshold": 1, "target": "vi-1"}, _line1()["search_state"])
    assert r["supported"] is False and "unknown metric" in r["reason"]


def test_wrong_subject_target_rejected():
    # unknown battlefield id → unsupported with a helpful reason.
    r = sm.evaluate_clause({"metric": "my_might_on_battlefield", "comparator": ">=", "threshold": 1, "target": "battlefield-z"}, _line1()["search_state"])
    assert r["supported"] is False and "unknown battlefield" in r["reason"]
    # player metric with a non-player target → rejected.
    r2 = sm.evaluate_clause({"metric": "score", "comparator": ">=", "threshold": 1, "target": "vi-1"}, _line1()["search_state"])
    assert r2["supported"] is False


# ── run_search_for: combine, ranking, notes ───────────────────────────────────


def test_combine_all_is_weakest_link():
    # line-1: control b (met, 1.0) AND opponent hand <= 4 (partial, hand=5).
    res = sm.run_search_for(
        _corpus(),
        [
            {"metric": "i_control_battlefield", "comparator": "==", "threshold": 1, "target": "battlefield-b", "label": "hold-b"},
            {"metric": "cards_in_hand", "comparator": "<=", "threshold": 4, "target": "opponent", "label": "empty-hand"},
        ],
        combine="all",
    )
    l1 = next(m for m in res["matches"] if m["line_id"] == "line-1")
    assert l1["hard_match"] is False
    # weakest link: min(1.0, partial) == the empty-hand clause satisfaction.
    empty = next(c for c in l1["clauses"] if c["label"] == "empty-hand")
    assert l1["satisfaction"] == pytest.approx(empty["satisfaction"])


def test_combine_any_takes_best_clause():
    res = sm.run_search_for(
        _corpus(),
        [
            {"metric": "i_control_battlefield", "comparator": "==", "threshold": 1, "target": "battlefield-b"},
            {"metric": "cards_in_hand", "comparator": "<=", "threshold": 2, "target": "opponent"},
        ],
        combine="any",
    )
    l1 = next(m for m in res["matches"] if m["line_id"] == "line-1")
    assert l1["satisfaction"] == pytest.approx(1.0)  # control-b clause is fully met


def test_hard_match_and_ranking():
    # line-2 fully satisfies: vi-1 dead AND opponent hand <= 2 AND scored >= 3.
    res = sm.run_search_for(
        _corpus(),
        [
            {"metric": "unit_alive", "comparator": "==", "threshold": 0, "target": "vi-1", "label": "kill-vi"},
            {"metric": "cards_in_hand", "comparator": "<=", "threshold": 2, "target": "opponent"},
            {"metric": "points_scored", "comparator": ">=", "threshold": 3},
        ],
        combine="all",
    )
    top = res["matches"][0]
    assert top["line_id"] == "line-2" and top["hard_match"] is True and top["satisfaction"] == pytest.approx(1.0)


def test_min_satisfaction_floor_demands_full():
    res = sm.run_search_for(
        _corpus(),
        [{"metric": "unit_alive", "comparator": "==", "threshold": 0, "target": "vi-1"}],
        min_satisfaction=1.0,
    )
    # only line-2 has vi-1 dead → fully satisfied; line-1 (vi-1 alive) drops out.
    assert [m["line_id"] for m in res["matches"]] == ["line-2"]


def test_note_names_binding_constraint_when_none_fully_satisfy():
    res = sm.run_search_for(
        _corpus(),
        [{"metric": "opponent_might_on_battlefield", "comparator": ">=", "threshold": 99, "target": "battlefield-b"}],
    )
    assert res["matches"] == [] or all(not m["hard_match"] for m in res["matches"])
    assert "0 fully satisfy" in res["note"]


def test_note_flags_unusable_constraint():
    res = sm.run_search_for(
        _corpus(),
        [{"metric": "bogus_metric", "comparator": ">=", "threshold": 1}],
    )
    assert "Unusable constraints" in res["note"]
    assert all(m["satisfaction"] == 0.0 for m in res["matches"]) or res["matches"] == []


def test_empty_constraints_errors():
    res = sm.run_search_for(_corpus(), [])
    assert "error" in res


def test_too_many_constraints_truncated():
    clauses = [{"metric": "points_scored", "comparator": ">=", "threshold": 0}] * 8
    res = sm.run_search_for(_corpus(), clauses)
    assert len(res["query"]["constraints"]) == sm.MAX_CONSTRAINTS
    assert "first" in res["note"]


# ── skills.search_for wiring + PredicateClause normalization ──────────────────


def test_skill_search_for_normalizes_and_filters(monkeypatch):
    skills.set_search_corpus(_corpus())
    try:
        res = skills.search_for(
            constraints=[
                # 'at_least' + 'high' exercise the PredicateClause synonym normalizers.
                {"metric": "unit_might", "comparator": "at_least", "threshold": 4, "target": "vi-1", "weight": "high"},
            ],
        )
        assert res["corpus_size"] == 2
        l1 = next(m for m in res["matches"] if m["line_id"] == "line-1")
        assert l1["clauses"][0]["met"] is True
    finally:
        skills.set_search_corpus(None)


def test_skill_search_for_no_corpus():
    skills.set_search_corpus(None)
    res = skills.search_for(constraints=[{"metric": "points_scored", "comparator": ">=", "threshold": 1}])
    assert res["corpus_size"] == 0 and res["matches"] == []


def test_skill_search_for_all_invalid_clauses():
    skills.set_search_corpus(_corpus())
    try:
        res = skills.search_for(constraints=["not-a-dict", 42])
        assert res["matches"] == [] and "at least one valid constraint" in res["note"]
    finally:
        skills.set_search_corpus(None)
