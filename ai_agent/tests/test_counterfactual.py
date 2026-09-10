"""Same-turn counterfactual: predicate packs, guards, comparison, abstentions."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_agent.analysis import counterfactual as cf
from ai_agent.analysis import predicate_packs as packs
from ai_agent.analysis.rollout_contracts import (
    HORIZON_ONE_PLAYER_TURN,
    INFORMATION_PUBLIC,
    OPPONENT_POLICY_NONE,
)
from ai_agent.memory import Memory


def _root_state() -> dict:
    return {
        "victory_score": 8,
        "players": {"me": {"score": 6, "cards_in_hand": 2, "ready_runes": 1},
                    "opponent": {"score": 4, "cards_in_hand": 3, "ready_runes": 0}},
        "units": {
            "vi-destructive": {"owner": "me", "might": 5, "damage": 0, "health": 5, "battlefield": "battlefield-a"},
            "enemy-bruiser": {"owner": "opponent", "might": 4, "damage": 0, "health": 4, "battlefield": "battlefield-b"},
        },
        "battlefields": {
            "battlefield-a": {"i_control": True, "controller": "me", "my_units": 1, "opp_units": 0, "my_might": 5, "opp_might": 0},
            "battlefield-b": {"i_control": False, "controller": "opponent", "my_units": 0, "opp_units": 1, "my_might": 0, "opp_might": 4},
        },
        "turn": {"points_scored": 0, "enemy_units_killed": 0, "battlefields_conquered": 0},
        "cards_played": [],
    }


def _line(moves, search_state, *, score=1.0, line_id="L"):
    return {
        "line_id": line_id,
        "moves": moves,
        "score": score,
        "search_state": search_state,
        "resolved_state": {},
        "canonical_moves": packs.canonical_moves(moves),
        "leaf_hash": "h",
    }


def test_pass_only_defensive_line_is_rejected():
    root = _root_state()
    leaf = {
        **root,
        "units": {"vi-destructive": root["units"]["vi-destructive"]},  # enemy gone? no, still both if we pass
    }
    # Pass "preserves" vi without doing anything.
    pack = packs.pack_preserve_with_progress(root, unit_id="vi-destructive", played_score=6)[0]
    line = _line(["pass", "end turn"], leaf)
    guard = packs.eligibility_guard(line, root_state=root, pack=pack, victory_score=8)
    assert guard["eligible"] is False
    assert guard["reason"] == "pass_only_non_terminal"


def test_win_now_terminal_is_eligible():
    root = _root_state()
    leaf = {
        **root,
        "players": {"me": {"score": 8, "cards_in_hand": 1, "ready_runes": 0},
                    "opponent": {"score": 4, "cards_in_hand": 3, "ready_runes": 0}},
        "game_over": True,
        "winner_index": 0,
    }
    pack = packs.pack_win_now(root, victory_score=8)
    line = _line(["move vi-destructive to battlefield-b", "end turn"], leaf, line_id="win")
    matches = cf.evaluate_pack_on_lines(pack, [line], root_state=root, victory_score=8)
    assert matches and matches[0]["eligibility"]["eligible"] is True


def test_original_beam_vs_offline_only_classify_differently():
    root = _root_state()
    win_leaf = {
        **root,
        "players": {"me": {"score": 8}, "opponent": {"score": 4}},
    }
    played = _line(["end turn"], root, score=1.0, line_id="played")
    original = [
        played,
        _line(["pass"], root, score=0.5, line_id="orig-pass"),
    ]
    offline_only = _line(
        ["move vi-destructive to battlefield-b", "end turn"],
        win_leaf,
        score=100.0,
        line_id="offline-win",
    )
    cmp_ = cf.compare_lines(
        played=played,
        original=original,
        offline=[offline_only],
        root_state=root,
        victory_score=8,
        played_score=6,
    )
    win_pack = next(p for p in cmp_["packs"] if p["pack_id"] == "win_now")
    assert win_pack["offline_found_hard_match"] is True
    assert win_pack["original_beam_had_hard_match"] is False
    assert win_pack["best_offline_in_original_beam"] is False

    both = cf.compare_lines(
        played=played,
        original=original + [offline_only],
        offline=[offline_only],
        root_state=root,
        victory_score=8,
        played_score=6,
    )
    win_both = next(p for p in both["packs"] if p["pack_id"] == "win_now")
    assert win_both["original_beam_had_hard_match"] is True
    assert win_both["best_offline_in_original_beam"] is True


def test_base_vs_overlay_goal_steering_detected():
    root = _root_state()
    win_leaf = {**root, "players": {"me": {"score": 8}, "opponent": {"score": 4}}}
    overlay_miss = _line(["end turn"], root, score=5.0, line_id="overlay")
    base_hit = _line(["move vi-destructive to battlefield-b"], win_leaf, score=9.0, line_id="base")
    cmp_ = cf.compare_lines(
        played=overlay_miss,
        original=[overlay_miss],
        offline=[overlay_miss],
        offline_base=[base_hit],
        root_state=root,
        victory_score=8,
        played_score=6,
    )
    win_pack = next(p for p in cmp_["packs"] if p["pack_id"] == "win_now")
    assert win_pack["offline_found_hard_match"] is False
    assert win_pack["base_found_hard_match"] is True


def test_legacy_and_hash_mismatch_abstain(tmp_path: Path):
    mem = Memory(db_path=tmp_path / "cf.db")
    # No snapshot at all.
    result = cf.analyze_decision(
        mem, game_id="g", turn=1, decision_index=0, persist=True, host_factory=None,
        force_same_turn=True,
    )
    assert result["status"] == cf.STATUS_NO_SNAPSHOT
    assert result["ok"] is False
    assert result["assumptions"]["horizon"] == HORIZON_ONE_PLAYER_TURN
    assert result["assumptions"]["opponent_policy"] == OPPONENT_POLICY_NONE
    assert result["assumptions"]["information_mode"] == INFORMATION_PUBLIC

    mem.record_decision_snapshot(
        game_id="g2",
        turn=2,
        decision_index=0,
        scalars={"my_score": 1},
        brief_state={"my_player_index": 0, "victory_score": 8},
        analysis_state={"schema_version": "1", "replay": {"supported": True}},
        analysis_state_schema_version="1",
        root_state_hash="expected",
    )
    mem.record_search_decision(
        game_id="g2", turn=2, decision_index=0, decision_type="main_phase",
        mode="main", my_player_index=0, chosen_line_id="L1", chosen_line_score=1.0,
        best_candidate_score=1.0, regret=0.0, score_margin=0.0, num_candidates=1,
        chosen_breakdown=None, chosen_features=None, search_stats=None,
        selector_source="argmax", selector_reasoning="", origin="self_play",
        weight_version_id=None, candidates=[{"line_id": "L1", "rank": 0, "score": 1.0,
                                             "chosen": True, "moves": ["end turn"]}],
    )

    @contextmanager
    def bad_hash_host(**_kwargs):
        class H:
            payload = {"ok": True, "root_state_hash": "other", "engine_port": 1}
        yield H()

    with patch("ai_agent.analysis.counterfactual.run_offline_search", return_value={"candidate_lines": []}):
        result = cf.analyze_decision(
            mem, game_id="g2", turn=2, decision_index=0, persist=True, host_factory=bad_hash_host,
            force_same_turn=True,
        )
    assert result["status"] == cf.STATUS_HASH_MISMATCH


def test_logged_goal_pack_from_goalset():
    goal_set = {
        "goals": [
            {"id": "pts", "kind": "state_target", "metric": "my_score", "comparator": ">=", "threshold": 8},
            {"id": "bias", "kind": "weight_bias", "feature": "battlefield_control"},
        ]
    }
    built = packs.pack_logged_goal(goal_set)
    assert len(built) == 1
    assert built[0]["constraints"][0]["metric"] == "score"
    assert built[0]["constraints"][0]["target"] == "me"
