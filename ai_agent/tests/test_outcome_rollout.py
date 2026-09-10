"""Outcome rollout helpers: root diversity, tiers, contracts, API shapes."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from ai_agent.analysis import outcome_tiers
from ai_agent.analysis.context import diversify_roots, first_strategic_move
from ai_agent.analysis.rollout_contracts import (
    HARD_CAP_FUTURE_PLAYER_TURNS,
    RESULT_SCHEMA_V2,
    clamp_future_player_turns,
    resolve_budget,
    v2_assumptions,
)
from ai_agent.memory import Memory


def test_diversify_roots_prefers_distinct_first_actions():
    played = {"line_id": "P", "moves": ["play a", "end turn"], "score": 1, "chosen": True}
    original = [
        played,
        {"line_id": "A", "moves": ["play a", "move x", "end turn"], "score": 2},
        {"line_id": "B", "moves": ["play b", "end turn"], "score": 3},
        {"line_id": "C", "moves": ["play c", "end turn"], "score": 4},
    ]
    roots = diversify_roots(played=played, original=original, offline=[], root_alt_cap=2)
    assert roots[0]["is_played"] is True
    alts = [r for r in roots if not r.get("is_played")]
    assert len(alts) == 2
    firsts = {first_strategic_move(r["moves"]) for r in alts}
    assert "play a" not in firsts or len(firsts) >= 1
    assert "play b" in firsts or "play c" in firsts


def test_diversify_roots_prefers_offline_new_first_actions():
    played = {"line_id": "P", "moves": ["play a", "end turn"], "chosen": True}
    original = [
        played,
        {"line_id": "A", "moves": ["play a", "move x", "end turn"]},
    ]
    offline = [
        {"line_id": "off-b", "moves": ["play b", "end turn"], "score": 4},
        {"line_id": "off-c", "moves": ["play c", "end turn"], "score": 5},
    ]
    roots = diversify_roots(
        played=played, original=original, offline=offline, root_alt_cap=2
    )
    alts = [r for r in roots if not r.get("is_played")]
    firsts = {first_strategic_move(r["moves"]) for r in alts}
    assert "play b" in firsts
    assert "play c" in firsts


def test_clamp_and_budget_presets():
    assert clamp_future_player_turns(99) == HARD_CAP_FUTURE_PLAYER_TURNS
    assert clamp_future_player_turns(0) == 1
    deep = resolve_budget("deep")
    fast = resolve_budget("fast")
    assert fast.global_node_budget < deep.global_node_budget
    assert deep.opponent_top_n == 3
    assert deep.seat_top_n == 2


def test_outcome_tiers_possible_policy_robust():
    target = {"kind": "win"}
    win_state = {
        "game_over": True,
        "winner_index": 0,
        "players": {"me": {"score": 8}, "opponent": {"score": 2}},
        "battlefields": {},
    }
    lose_state = {
        "game_over": True,
        "winner_index": 1,
        "players": {"me": {"score": 2}, "opponent": {"score": 8}},
        "battlefields": {},
    }
    roots = [
        {"line_id": "played", "is_played": True, "moves": ["end turn"]},
        {"line_id": "alt", "is_played": False, "moves": ["play x", "end turn"]},
    ]
    paths = [
        {
            "line_id": "pv-1",
            "root_line_id": "played",
            "score": 1.0,
            "moves": ["end turn"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["end turn"], "seat": 0},
                {"line_id": "line-1", "kind": "main", "moves": ["end turn"], "seat": 1},
            ],
            "search_state": lose_state,
            "terminal_reason": "game_over",
            "depth_player_turns": 2,
        },
        {
            "line_id": "pv-2",
            "root_line_id": "alt",
            "score": 9.0,
            "moves": ["play x", "end turn"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["play x", "end turn"], "seat": 0},
                {"line_id": "line-1", "kind": "main", "moves": ["end turn"], "seat": 1},
            ],
            "search_state": win_state,
            "terminal_reason": "game_over",
            "depth_player_turns": 2,
        },
        {
            "line_id": "pv-3",
            "root_line_id": "alt",
            "score": 8.0,
            "moves": ["play x", "end turn", "pass"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["play x", "end turn"], "seat": 0},
                {"line_id": "line-2", "kind": "main", "moves": ["play y", "end turn"], "seat": 1},
            ],
            "search_state": win_state,
            "terminal_reason": "game_over",
            "depth_player_turns": 2,
        },
    ]
    report = outcome_tiers.classify_all_roots(
        roots=roots, paths=paths, target=target, seat=0, opponent_top_n=3
    )
    assert report["any_possible_improvement"] is True
    alt = next(r for r in report["by_root"] if r["root_line_id"] == "alt")
    assert alt["possible"] is True
    assert alt["policy_likely"] is True
    # Both opponent groups have a win → robust
    assert alt["robust"] is True


def test_policy_likely_ignores_cooperative_opponent_skip():
    """A win that needs the opponent to pass is possible, not policy-likely."""
    target = {"kind": "win"}
    win_state = {
        "game_over": True,
        "winner_index": 0,
        "players": {"me": {"score": 8}, "opponent": {"score": 2}},
        "battlefields": {},
    }
    lose_state = {
        "game_over": True,
        "winner_index": 1,
        "players": {"me": {"score": 2}, "opponent": {"score": 8}},
        "battlefields": {},
    }
    roots = [{"line_id": "alt", "is_played": False, "moves": ["play x", "end turn"]}]
    paths = [
        {
            "line_id": "pv-coop",
            "root_line_id": "alt",
            "score": 12.0,
            "moves": ["play x", "end turn"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["play x", "end turn"], "seat": 0},
                {"line_id": "line-2", "kind": "main", "moves": ["end turn"], "seat": 1},
            ],
            "search_state": win_state,
            "terminal_reason": "game_over",
            "depth_player_turns": 2,
        },
        {
            "line_id": "pv-policy",
            "root_line_id": "alt",
            "score": 1.0,
            "moves": ["play x", "end turn", "play y"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["play x", "end turn"], "seat": 0},
                {"line_id": "line-1", "kind": "main", "moves": ["play y", "end turn"], "seat": 1},
            ],
            "search_state": lose_state,
            "terminal_reason": "game_over",
            "depth_player_turns": 2,
        },
    ]
    report = outcome_tiers.classify_all_roots(
        roots=roots, paths=paths, target=target, seat=0, opponent_top_n=3
    )
    alt = report["by_root"][0]
    assert alt["possible"] is True
    assert alt["policy_likely"] is False
    reps = alt["representative_paths"]
    assert reps["possible"]["line_id"] == "pv-coop"
    assert reps["policy_likely"] is None
    assert reps["policy_pv"]["line_id"] == "pv-policy"
    assert report["improved_roots"] == []
    assert "alt" in report["possible_only_roots"]


def test_max_score_after_turns_picks_policy_and_best():
    """Maximize my_score after N turns; policy is rank-1, possible is the high score."""
    target = {"kind": "max_score_after_turns", "after_player_turns": 2, "metric": "my_score"}
    played_state = {
        "players": {"me": {"score": 2}, "opponent": {"score": 2}},
        "battlefields": {},
    }
    alt_policy_state = {
        "players": {"me": {"score": 3}, "opponent": {"score": 1}},
        "battlefields": {},
    }
    alt_coop_state = {
        "players": {"me": {"score": 5}, "opponent": {"score": 0}},
        "battlefields": {},
    }
    roots = [
        {"line_id": "played", "is_played": True, "moves": ["end turn"]},
        {"line_id": "alt", "is_played": False, "moves": ["play x", "end turn"]},
    ]
    paths = [
        {
            "line_id": "pv-played",
            "root_line_id": "played",
            "is_policy_pv": True,
            "opp_policy_rank": 1,
            "our_policy_rank": 1,
            "score": 1.0,
            "moves": ["end turn"],
            "path_segments": [
                {"line_id": "played", "kind": "root", "moves": ["end turn"], "seat": 0},
                {"line_id": "line-1", "kind": "main", "moves": ["end turn"], "seat": 1},
            ],
            "search_state": played_state,
            "depth_player_turns": 2,
        },
        {
            "line_id": "pv-alt-policy",
            "root_line_id": "alt",
            "is_policy_pv": True,
            "opp_policy_rank": 1,
            "our_policy_rank": 1,
            "score": 2.0,
            "moves": ["play x", "end turn"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["play x", "end turn"], "seat": 0},
                {"line_id": "line-1", "kind": "main", "moves": ["play y", "end turn"], "seat": 1},
            ],
            "search_state": alt_policy_state,
            "depth_player_turns": 2,
        },
        {
            "line_id": "pv-alt-coop",
            "root_line_id": "alt",
            "is_policy_pv": False,
            "opp_policy_rank": 2,
            "our_policy_rank": 1,
            "score": 9.0,
            "moves": ["play x", "end turn", "pass"],
            "path_segments": [
                {"line_id": "line-1", "kind": "root", "moves": ["play x", "end turn"], "seat": 0},
                {"line_id": "line-2", "kind": "main", "moves": ["end turn"], "seat": 1},
            ],
            "search_state": alt_coop_state,
            "depth_player_turns": 2,
        },
    ]
    report = outcome_tiers.classify_all_roots(
        roots=roots, paths=paths, target=target, seat=0, opponent_top_n=3
    )
    played = next(r for r in report["by_root"] if r["root_line_id"] == "played")
    alt = next(r for r in report["by_root"] if r["root_line_id"] == "alt")
    assert played["policy_value"] == 2.0
    assert alt["policy_value"] == 3.0
    assert alt["possible_value"] == 5.0
    assert alt["policy_likely"] is True
    assert alt["possible"] is True
    assert report["improved_roots"] == ["alt"]
    assert alt["representative_paths"]["policy_pv"]["line_id"] == "pv-alt-policy"
    assert alt["representative_paths"]["possible"]["line_id"] == "pv-alt-coop"


def test_until_turn_means_that_game_turn_ends():
    """N=4 is eligible only after turn 4 has ended (checkpoint turn_number > 4)."""
    target = {"kind": "max_score_after_turns", "until_turn": 4, "metric": "my_score"}
    still_on_4 = {
        "checkpoint": {"turn_number": 4},
        "search_state": {"players": {"me": {"score": 9}, "opponent": {"score": 0}}},
        "depth_player_turns": 3,
    }
    assert outcome_tiers.path_objective_value(still_on_4, target, seat=0) is None
    after_4 = {
        "checkpoint": {"turn_number": 5},
        "search_state": {"players": {"me": {"score": 3}, "opponent": {"score": 1}}},
        "depth_player_turns": 3,
    }
    assert outcome_tiers.path_objective_value(after_4, target, seat=0) == 3.0
    over = {
        "terminal_reason": "game_over",
        "search_state": {
            "game_over": True,
            "players": {"me": {"score": 8}, "opponent": {"score": 2}},
        },
        "depth_player_turns": 1,
    }
    assert outcome_tiers.path_objective_value(over, target, seat=0) == 8.0
    assert outcome_tiers.horizon_player_turns_for_until(
        current_turn=2, until_turn=4, hard_cap=6
    ) == 3
    assert outcome_tiers.horizon_player_turns_for_until(
        current_turn=4, until_turn=4, hard_cap=6
    ) == 1


def test_max_score_skips_paths_short_of_n():
    target = {"kind": "max_score_after_turns", "after_player_turns": 4}
    path = {
        "search_state": {"players": {"me": {"score": 9}, "opponent": {"score": 0}}},
        "depth_player_turns": 2,
    }
    assert outcome_tiers.path_objective_value(path, target, seat=0) is None
    path["depth_player_turns"] = 4
    assert outcome_tiers.path_objective_value(path, target, seat=0) == 9.0
    lead = {"kind": "max_score_after_turns", "after_player_turns": 4, "metric": "score_diff"}
    assert outcome_tiers.path_objective_value(path, lead, seat=0) == 9.0
    path["score"] = 12.5
    pos = {"kind": "max_score_after_turns", "after_player_turns": 4, "metric": "position"}
    assert outcome_tiers.path_objective_value(path, pos, seat=0) == 12.5


def test_control_battlefield_target():
    path = {
        "search_state": {
            "battlefields": {
                "battlefield-a": {"i_control": True},
                "battlefield-b": {"i_control": False},
            },
            "players": {"me": {"score": 3}},
        },
        "depth_player_turns": 2,
    }
    assert outcome_tiers.evaluate_target_on_path(
        path, {"kind": "control_battlefield", "battlefield_id": "battlefield-a"}, seat=0
    )
    assert not outcome_tiers.evaluate_target_on_path(
        path, {"kind": "control_battlefield", "battlefield_id": "battlefield-b"}, seat=0
    )


def test_v2_assumptions_stamp():
    a = v2_assumptions(future_player_turns=4)
    assert a["horizon"] == "multi_turn"
    assert a["opponent_policy"] == "oracle"
    assert a["information_mode"] == "oracle_hidden_state"
    assert a["result_schema_version"] == RESULT_SCHEMA_V2
    assert a["policy_bounded"] is True


def test_memory_list_counterfactual_runs(tmp_path: Path):
    mem = Memory(db_path=tmp_path / "cf.db")
    mem.record_counterfactual_run(
        game_id="g",
        turn=1,
        decision_index=0,
        root_state_hash="h",
        predicate_pack_version="1",
        search_inputs={"mode": "outcome_rollout"},
        profile_inputs={},
        budget={"frontier_cap": 24},
        assumptions=v2_assumptions(future_player_turns=4),
        status="ok",
        result={"ok": True, "run_kind": "outcome_rollout", "future_player_turns": 4},
        run_kind="outcome_rollout",
        result_schema_version="2",
        future_player_turns=4,
        opponent_policy="oracle",
    )
    rows = mem.list_counterfactual_runs(game_id="g", turn=1, decision_index=0)
    assert len(rows) == 1
    assert rows[0]["run_kind"] == "outcome_rollout"
    assert rows[0]["future_player_turns"] == 4
    assert rows[0]["result"] is None
    fat = mem.list_counterfactual_runs(
        game_id="g", turn=1, decision_index=0, include_result=True,
    )
    assert fat[0]["result"]["ok"] is True
    one = mem.get_counterfactual_run(rows[0]["id"])
    assert one is not None
    assert one["result"]["ok"] is True


def test_analyze_decision_routes_same_turn(tmp_path: Path):
    from ai_agent.analysis import counterfactual as cf

    mem = Memory(db_path=tmp_path / "cf2.db")
    result = cf.analyze_decision(
        mem,
        game_id="missing",
        turn=1,
        decision_index=0,
        persist=False,
        force_same_turn=True,
    )
    assert result["run_kind"] == "same_turn"
    assert result["ok"] is False


def test_outcome_rollout_fallback_on_engine_error(tmp_path: Path):
    from ai_agent.analysis import outcome_rollout as ocr

    mem = Memory(db_path=tmp_path / "cf3.db")
    mem.record_decision_snapshot(
        game_id="g",
        turn=1,
        decision_index=0,
        scalars={"my_score": 1},
        brief_state={"my_player_index": 0, "victory_score": 8},
        analysis_state={"schema_version": "1", "replay": {"supported": True}},
        analysis_state_schema_version="1",
        root_state_hash="hash",
    )
    mem.record_search_decision(
        game_id="g",
        turn=1,
        decision_index=0,
        decision_type="main_phase",
        mode="main",
        my_player_index=0,
        chosen_line_id="L1",
        chosen_line_score=1.0,
        best_candidate_score=1.0,
        regret=0.0,
        score_margin=0.0,
        num_candidates=1,
        chosen_breakdown=None,
        chosen_features=None,
        search_stats=None,
        selector_source="argmax",
        selector_reasoning="",
        origin="self_play",
        weight_version_id=None,
        candidates=[{
            "line_id": "L1",
            "rank": 0,
            "score": 1.0,
            "chosen": True,
            "moves": ["end turn"],
        }],
    )

    from contextlib import contextmanager

    @contextmanager
    def boom_host(**_kwargs):
        raise RuntimeError("no godot")
        yield  # pragma: no cover

    with patch.object(ocr.cf, "open_counterfactual_host", boom_host):
        with patch.object(
            ocr.cf,
            "analyze_same_turn_decision",
            return_value={"ok": False, "status": "engine_error", "run_kind": "same_turn"},
        ):
            result = ocr.analyze_outcome_rollout(
                mem,
                game_id="g",
                turn=1,
                decision_index=0,
                persist=False,
                host_factory=boom_host,
                include_same_turn=True,
            )
    assert result["status"] == "engine_error"
    assert result.get("same_turn_fallback") is not None
