"""Deterministic failure-mode classification + CF upgrades."""
from __future__ import annotations

from ai_agent.analysis import failure_modes as fm


def _bundle(**overrides) -> dict:
    base = {
        "game_id": "g1",
        "turn": 4,
        "decision_index": 1,
        "search_decision": {
            "regret": 0.0,
            "num_candidates": 3,
            "selector_source": "argmax",
            "game_outcome": "loss",
            "goals_source": "none",
            "goal_set_json": None,
            "overlay_json": None,
            "chosen_goal_achieved_json": None,
            "search_stats_json": {"stopped_reason": "exhausted"},
        },
        "candidates": [
            {"line_id": "L1", "chosen": True, "moves": ["end turn"], "score": 10.0},
            {"line_id": "L2", "chosen": False, "moves": ["play x"], "score": 9.0},
        ],
        "eval_metrics": {"parse_retries": 0, "legality_retries": 0, "fell_back_to_pass": 0},
        "client_metrics": {"heuristic_fallback": 0, "rejection_retries": 0, "accepted": 1},
        "reasoner": None,
    }
    base.update(overrides)
    return base


def test_reliability_signal():
    report = fm.classify_with_counterfactual(_bundle(
        eval_metrics={"parse_retries": 2, "legality_retries": 1, "fell_back_to_pass": 1},
        client_metrics={"heuristic_fallback": 1, "rejection_retries": 3, "accepted": 0},
        search_decision={
            **_bundle()["search_decision"],
            "selector_source": "fallback",
            "game_outcome": None,
            "regret": None,
        },
    ))
    modes = [f["mode"] for f in report["findings"]]
    assert "reliability" in modes
    rel = next(f for f in report["findings"] if f["mode"] == "reliability")
    assert rel["confidence"] == "high"
    assert rel["recommended_fix_surface"] == "engine_or_agent_reliability"


def test_reasoner_investigation_and_commit():
    report = fm.classify_with_counterfactual(_bundle(
        reasoner={
            "investigation_satisfied": 0,
            "local_fork_attempted": 0,
            "comparison_required": 1,
            "failed_search_calls": 3,
            "recovered_failed_searches": 1,
            "committed": 1,
            "chosen_line_complete": 0,
            "terminal_kind": "line",
        },
        search_decision={**_bundle()["search_decision"], "game_outcome": None, "regret": 0.0},
    ))
    modes = [f["mode"] for f in report["findings"]]
    assert "reasoner_investigation" in modes
    assert "reasoner_commit" in modes


def test_selection_error_requires_non_argmax():
    llm = fm.classify_with_counterfactual(_bundle(
        search_decision={
            **_bundle()["search_decision"],
            "regret": 4.0,
            "selector_source": "llm",
            "num_candidates": 5,
            "game_outcome": None,
        }
    ))
    assert any(f["mode"] == "selection_error" for f in llm["findings"])

    argmax = fm.classify_with_counterfactual(_bundle(
        search_decision={
            **_bundle()["search_decision"],
            "regret": 4.0,
            "selector_source": "argmax",
            "num_candidates": 5,
            "game_outcome": None,
        }
    ))
    assert not any(f["mode"] == "selection_error" for f in argmax["findings"])


def test_goal_leaf_miss():
    report = fm.classify_with_counterfactual(_bundle(
        search_decision={
            **_bundle()["search_decision"],
            "goal_set_json": {"goals": [{"id": "pts"}]},
            "chosen_goal_achieved_json": {"pts": {"met": False, "satisfaction": 0.2}},
            "game_outcome": None,
            "regret": 0.0,
        }
    ))
    assert any(f["mode"] == "goal_leaf_miss" for f in report["findings"])


def test_loss_without_cf_does_not_imply_eval_or_search():
    report = fm.classify_with_counterfactual(_bundle())
    modes = [f["mode"] for f in report["findings"]]
    assert "eval_error" not in modes
    assert "search_coverage_error" not in modes
    assert any(a["abstention_reason"] == "loss_or_zero_regret_without_counterfactual" for a in report["abstentions"])


def test_cf_upgrades_search_vs_eval_vs_selection():
    offline_win = {
        "ok": True,
        "status": "ok",
        "comparison": {
            "packs": [{
                "pack_id": "win_now",
                "offline_found_hard_match": True,
                "original_beam_had_hard_match": False,
                "best_offline_in_original_beam": False,
                "base_found_hard_match": False,
                "offline_hard_matches": [{"canonical_moves": ["move x", "end turn"]}],
                "original_hard_matches": [],
            }]
        },
    }
    coverage = fm.classify_with_counterfactual(_bundle(search_decision={
        **_bundle()["search_decision"], "game_outcome": "loss", "regret": 0.0,
    }), offline_win)
    modes = [f["mode"] for f in coverage["findings"]]
    assert "missed_same_turn_goal" in modes
    assert "search_coverage_error" in modes
    assert "eval_error" not in modes

    orig_hard = {
        "ok": True,
        "status": "ok",
        "comparison": {
            "packs": [{
                "pack_id": "win_now",
                "offline_found_hard_match": True,
                "original_beam_had_hard_match": True,
                "best_offline_in_original_beam": True,
                "base_found_hard_match": True,
                "offline_hard_matches": [{"canonical_moves": ["move x"]}],
                "original_hard_matches": [{"canonical_moves": ["move x"]}],
            }]
        },
    }
    eval_rep = fm.classify_with_counterfactual(_bundle(
        search_decision={**_bundle()["search_decision"], "selector_source": "argmax", "game_outcome": None, "regret": 0.0},
        candidates=[{"line_id": "L1", "chosen": True, "moves": ["end turn"]}],
    ), orig_hard)
    modes = [f["mode"] for f in eval_rep["findings"]]
    assert "eval_error" in modes
    assert "selection_error" not in modes

    sel_rep = fm.classify_with_counterfactual(_bundle(
        search_decision={**_bundle()["search_decision"], "selector_source": "llm", "game_outcome": None, "regret": 2.0},
        candidates=[{"line_id": "L1", "chosen": True, "moves": ["end turn"]}],
    ), orig_hard)
    modes = [f["mode"] for f in sel_rep["findings"]]
    assert "selection_error" in modes


def test_goal_error_when_base_finds_overlay_misses():
    cf_result = {
        "ok": True,
        "status": "ok",
        "comparison": {
            "packs": [{
                "pack_id": "win_now",
                "offline_found_hard_match": False,
                "original_beam_had_hard_match": False,
                "best_offline_in_original_beam": False,
                "base_found_hard_match": True,
                "offline_hard_matches": [],
                "original_hard_matches": [],
            }]
        },
    }
    report = fm.classify_with_counterfactual(_bundle(
        search_decision={
            **_bundle()["search_decision"],
            "overlay_json": {"weight_multipliers": {"state_weights.score_diff": 2.0}},
            "game_outcome": None,
            "regret": 0.0,
        },
        candidates=[{"line_id": "L1", "chosen": True, "moves": ["end turn"]}],
    ), cf_result)
    modes = [f["mode"] for f in report["findings"]]
    assert "goal_error" in modes
    assert "eval_error" not in modes
    assert "search_coverage_error" not in modes
