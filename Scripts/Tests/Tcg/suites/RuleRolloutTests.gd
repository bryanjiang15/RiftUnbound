class_name RuleRolloutTests
extends RefCounted

# Multi-turn / decision-boundary rollout primitives.

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const LineReplayerScript = preload("res://Scripts/Game/LineReplayer.gd")
const OutcomeRolloutScript = preload("res://Scripts/Game/OutcomeRollout.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")


static func run(assertions) -> void:
	_test_clone_copies_rng_seed(assertions)
	_test_line_replayer_basic(assertions)
	_test_decision_boundary_describe(assertions)
	_test_rollout_does_not_mutate_live(assertions)
	_test_rollout_respects_horizon_and_budgets(assertions)
	_test_opponent_main_turn_is_searched(assertions)


static func _load(h) -> void:
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")


static func _test_clone_copies_rng_seed(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	live.rng_seed = "seed-abc"
	live.rng_counter = 3
	var clone: GameState = live.clone()
	assertions.assert_eq(clone.rng_seed, "seed-abc", "clone copies rng_seed")
	assertions.assert_eq(clone.rng_counter, 3, "clone copies rng_counter")
	clone.rng_counter = 9
	assertions.assert_eq(live.rng_counter, 3, "clone rng_counter not aliased")


static func _test_line_replayer_basic(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var sig_before := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(live, 0))
	var replayer = LineReplayerScript.new()
	var result: Dictionary = replayer.replay_to_quiescence(live, ["end turn"], 0)
	assertions.assert_true(bool(result.get("ok", false)), "replay ok")
	assertions.assert_true(result.get("gs") != null, "returns gs")
	var sig_after := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(live, 0))
	assertions.assert_eq(sig_after, sig_before, "live unchanged after replay")


static func _test_decision_boundary_describe(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var sim = MoveSimulatorScript.new()
	var boundary: Dictionary = sim.describe_decision_boundary(live, 0)
	assertions.assert_eq(str(boundary.get("kind")), "main_turn", "neutral open is main_turn")
	assertions.assert_eq(int(boundary.get("acting_seat")), live.turn_player_index, "acting seat is turn player")


static func _test_rollout_does_not_mutate_live(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var before := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(live, 0))
	var roller = OutcomeRolloutScript.new()
	var payload: Dictionary = roller.search_rollout(live, 0, {
		"future_player_turns": 1,
		"frontier_cap": 4,
		"global_node_budget": 200,
		"global_time_ms": 2000,
		"seat_top_n": 1,
		"opponent_top_n": 1,
		"roots": [{"line_id": "played", "moves": ["end turn"], "source": "played"}],
		"per_turn_node_budget": 40,
		"per_turn_time_budget_ms": 200,
	})
	assertions.assert_true(bool(payload.get("ok", false)), "rollout ok")
	var after := ScoreModelScript.structural_hash(ScoreModelScript.snapshot(live, 0))
	assertions.assert_eq(after, before, "rollout does not mutate live")


static func _test_rollout_respects_horizon_and_budgets(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var roller = OutcomeRolloutScript.new()
	var payload: Dictionary = roller.search_rollout(live, 0, {
		"future_player_turns": 1,
		"frontier_cap": 2,
		"global_node_budget": 30,
		"global_time_ms": 1500,
		"seat_top_n": 1,
		"opponent_top_n": 1,
		"roots": [{"line_id": "played", "moves": ["end turn"], "source": "played"}],
		"per_turn_node_budget": 20,
		"per_turn_time_budget_ms": 150,
	})
	assertions.assert_true(bool(payload.get("ok", false)), "budgeted rollout ok")
	assertions.assert_eq(str(payload.get("horizon")), "multi_turn", "horizon stamp")
	assertions.assert_eq(str(payload.get("opponent_policy")), "oracle", "oracle stamp")
	var until_payload: Dictionary = roller.search_rollout(live, 0, {
		"future_player_turns": 3,
		"until_turn_number": int(live.turn_number) + 1,
		"frontier_cap": 2,
		"global_node_budget": 80,
		"global_time_ms": 1500,
		"seat_top_n": 1,
		"opponent_top_n": 1,
		"roots": [{"line_id": "played", "moves": ["end turn"], "source": "played"}],
		"per_turn_node_budget": 20,
		"per_turn_time_budget_ms": 150,
	})
	assertions.assert_eq(
		int(until_payload.get("until_turn_number", 0)),
		int(live.turn_number) + 1,
		"until_turn_number is stamped on rollout"
	)
	var stats: Dictionary = payload.get("search_stats", {})
	assertions.assert_true(int(stats.get("nodes_explored", 0)) >= 0, "nodes recorded")
	var tree: Dictionary = payload.get("rollout_tree", {})
	assertions.assert_true(tree.has("paths") or tree.has("nodes"), "tree present")


static func _test_opponent_main_turn_is_searched(assertions) -> void:
	# After P0 ends the turn, P1 has a ready unit that can move to a battlefield.
	# The oracle opponent policy must actually search that turn — not just skip.
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"turn_number": 1,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"score": 0, "hand": [], "base": [], "deck_size": 8, "rune_deck_size": 12},
			{
				"score": 0,
				"hand": [],
				"base": [{"id": "vi-destructive", "exhausted": false}],
				"deck_size": 8,
				"rune_deck_size": 12,
			},
		],
	})
	var roller = OutcomeRolloutScript.new()
	var payload: Dictionary = roller.search_rollout(h.gs(), 0, {
		"future_player_turns": 2,
		"frontier_cap": 8,
		"global_node_budget": 800,
		"global_time_ms": 4000,
		"seat_top_n": 1,
		"opponent_top_n": 3,
		"roots": [{"line_id": "played", "moves": ["end turn"], "source": "played"}],
		"per_turn_node_budget": 80,
		"per_turn_time_budget_ms": 800,
		"per_turn_max_depth": 8,
	})
	assertions.assert_true(bool(payload.get("ok", false)), "opponent-turn rollout ok")
	var found_opp_action := false
	var found_opp_segment := false
	for path in payload.get("principal_variations", payload.get("candidate_lines", [])):
		if typeof(path) != TYPE_DICTIONARY:
			continue
		for seg in path.get("path_segments", []):
			if typeof(seg) != TYPE_DICTIONARY:
				continue
			if int(seg.get("seat", -1)) != 1:
				continue
			found_opp_segment = true
			for m in seg.get("moves", []):
				var s := str(m)
				if s != "" and s != "end turn" and s != "pass" and not s.begins_with("choose "):
					found_opp_action = true
					break
			if found_opp_action:
				break
		if found_opp_action:
			break
	assertions.assert_true(found_opp_segment, "rollout records an opponent-seat segment")
	assertions.assert_true(found_opp_action, "opponent policy plays a real action, not only end turn")
	var pvs: Array = payload.get("principal_variations", [])
	if not pvs.is_empty() and typeof(pvs[0]) == TYPE_DICTIONARY:
		var first: Dictionary = pvs[0]
		assertions.assert_true(
			bool(first.get("is_policy_pv", false)) or int(first.get("opp_policy_rank", 99)) <= 1,
			"first PV is the opponent rank-1 policy, not the highest analyzed-seat score"
		)
