class_name RuleSearchTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const ScoringProfileScript = preload("res://Scripts/Game/ScoringProfile.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")


static func run(assertions) -> void:
	_test_search_finds_winning_line(assertions)
	_test_transposition_table_dedupes_reorderings(assertions)
	_test_search_does_not_mutate_live(assertions)
	_test_anytime_budget_returns_lines(assertions)
	_test_scoring_breakdown(assertions)
	_test_scoring_features_reward_outcomes(assertions)
	_test_scoring_keywords_on_board(assertions)
	_test_reactive_potential(assertions)
	_test_line_steps_parallel_and_labeled(assertions)
	_test_reactive_search_in_showdown_window(assertions)
	_test_discard_picks_best_card(assertions)


# A forced discard during search must be resolved greedily — keeping the card
# that best preserves the AI's position — rather than blindly discarding the
# first valid option. Here the hand holds a Reaction (gust, payable by the ready
# rune) listed FIRST and a do-nothing card (fading-memories) second. First-valid
# would dump the reaction and zero out reactive_potential; greedy must instead
# discard fading-memories and keep gust.
static func _test_discard_picks_best_card(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"hand": ["gust", "fading-memories"],
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"deck_size": 5, "rune_deck_size": 12
			},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var gs = h.gs()
	gs.pending_prompt = {
		"player_index": 0,
		"type": "choose_discard",
		"remaining": 1,
		"valid_choices": ["gust", "fading-memories"],
		"prompt": "[PROMPT] Choose a card to discard",
	}
	var sim = MoveSimulatorScript.new()
	sim.ai_index = 0
	var root_snapshot := ScoreModelScript.snapshot(gs, 0)
	var ranker := func(cand_gs: GameState) -> float:
		var snap := ScoreModelScript.snapshot(cand_gs, 0)
		return float(ScoringProfileScript.new().score_with_breakdown(
			ScoreModelScript.build_score_features(root_snapshot, snap, [])
		)["score"])
	var step := sim._resolve_ai_prompt(h.controller, ranker)
	assertions.assert_eq(str(step.get("command", "")), "choose fading-memories",
		"greedy discard keeps the reaction and discards the do-nothing card")
	var hand_ids: Array = []
	for c in gs.players[0].hand:
		hand_ids.append(c.instance_id)
	assertions.assert_true("gust" in hand_ids, "the reaction card remains in hand after greedy discard")


static func _hash(gs: GameState, player_index: int) -> String:
	return ScoreModelScript.structural_hash(ScoreModelScript.snapshot(gs, player_index))


static func _test_search_finds_winning_line(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {"node_budget": 80, "time_budget_ms": 1000, "beam_width": 6})
	var lines: Array = result.get("candidate_lines", [])
	assertions.assert_true(not lines.is_empty(), "search returns at least one candidate line")
	var best: Dictionary = lines[0]
	assertions.assert_true(best.get("resolved_state", {}).get("wins_game", false), "top line wins the game")


static func _test_transposition_table_dedupes_reorderings(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_reorderable.json")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {"node_budget": 80, "time_budget_ms": 500, "beam_width": 12, "max_depth": 3})
	var stats: Dictionary = result.get("search_stats", {})
	assertions.assert_true(int(stats.get("transposition_hits", 0)) > 0, "search TT dedupes reordered move sequences")


static func _test_search_does_not_mutate_live(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")
	var before := _hash(h.gs(), 0)
	var searcher = TurnSearchScript.new()
	var _result: Dictionary = searcher.search(h.gs(), 0, {"node_budget": 40, "time_budget_ms": 500})
	assertions.assert_eq(_hash(h.gs(), 0), before, "turn search leaves live state unchanged")


static func _test_anytime_budget_returns_lines(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_reorderable.json")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {"node_budget": 1, "time_budget_ms": 500, "beam_width": 4})
	assertions.assert_true(not result.get("candidate_lines", []).is_empty(), "anytime node budget still returns a candidate")
	assertions.assert_eq(result.get("search_stats", {}).get("stopped_reason", ""), "node_budget", "budget stop reason is reported")


static func _test_scoring_breakdown(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	var snapshot: Dictionary = ScoreModelScript.snapshot(h.gs(), 0)
	snapshot["game_over"] = true
	snapshot["winner_index"] = 0
	snapshot["my_score"] = 8
	var features: Dictionary = ScoreModelScript.build_score_features(snapshot, snapshot, [])
	var scorer = ScoringProfileScript.new()
	var result: Dictionary = scorer.score_with_breakdown(features)
	var breakdown: Dictionary = result.get("breakdown", {})
	assertions.assert_true(breakdown.has("win_game"), "scoring includes win_game term")
	assertions.assert_true(float(breakdown.get("win_game", 0.0)) >= 1000.0, "win_game dominates score")
	assertions.assert_true(breakdown.has("score_diff"), "scoring includes score_diff term")
	assertions.assert_true(breakdown.has("battlefield_conquered"), "scoring includes battlefield_conquered term")
	assertions.assert_true(breakdown.has("keywords"), "scoring includes keyword term")


static func _test_scoring_features_reward_outcomes(assertions) -> void:
	# Generic action/outcome features should each move the score in the expected
	# direction when fed hand-built root/leaf snapshots.
	var scorer = ScoringProfileScript.new()

	var root := _bare_snapshot(0)
	root["units"] = {
		"my-1": _unit(0, "battlefield-a", 3, []),
		"opp-1": _unit(1, "battlefield-a", 3, []),
	}
	root["bf"] = {"battlefield-a": -1, "battlefield-b": -1}

	# Leaf: killed the enemy unit, kept mine, conquered battlefield-a (scored it).
	var leaf := _bare_snapshot(0)
	leaf["units"] = {"my-1": _unit(0, "battlefield-a", 3, [])}
	leaf["bf"] = {"battlefield-a": 0, "battlefield-b": -1}
	leaf["bf_scored"] = ["battlefield-a"]
	leaf["my_score"] = 1

	var feats := ScoreModelScript.build_score_features(root, leaf, [])
	assertions.assert_eq(int(feats.get("enemy_units_killed", -1)), 1, "kill of enemy unit detected")
	assertions.assert_eq(int(feats.get("own_units_lost", -1)), 0, "own unit not counted as lost")
	assertions.assert_eq(int(feats.get("battlefields_conquered", -1)), 1, "scoring conquer detected")
	assertions.assert_eq(int(feats.get("points_scored", -1)), 1, "point gain detected")
	var killed_score := float(scorer.score_with_breakdown(feats).get("score", 0.0))

	# Same board but the conquered battlefield was ALREADY scored this turn — the
	# holding fix means it must NOT count as a fresh scoring conquer.
	var leaf2 := leaf.duplicate(true)
	leaf2["bf_scored"] = []
	var feats2 := ScoreModelScript.build_score_features(root, leaf2, [])
	assertions.assert_eq(int(feats2.get("battlefields_conquered", -1)), 0, "conquer of already-scored battlefield is not double-counted")

	# A do-nothing leaf (no kills, no conquer) must score lower than the winning trade.
	var idle := root.duplicate(true)
	var idle_feats := ScoreModelScript.build_score_features(root, idle, [])
	var idle_score := float(scorer.score_with_breakdown(idle_feats).get("score", 0.0))
	assertions.assert_true(killed_score > idle_score, "killing + conquering scores higher than idling")


static func _test_scoring_keywords_on_board(assertions) -> void:
	# Board keyword presence (field/base) should be a net me-vs-opponent term.
	var scorer = ScoringProfileScript.new()

	var base := _bare_snapshot(0)
	base["bf"] = {}
	var feats_plain := ScoreModelScript.build_score_features(base, base, [])
	var plain_score := float(scorer.score_with_breakdown(feats_plain).get("score", 0.0))

	var withkw := base.duplicate(true)
	withkw["units"] = {"my-1": _unit(0, "battlefield-a", 3, ["tank", "shield"])}
	var feats_kw := ScoreModelScript.build_score_features(withkw, withkw, [])
	assertions.assert_eq(int(feats_kw.get("keyword_net", {}).get("tank", 0)), 1, "tank keyword counted for my unit")
	assertions.assert_eq(int(feats_kw.get("keyword_net", {}).get("shield", 0)), 1, "shield keyword counted for my unit")
	var kw_score := float(scorer.score_with_breakdown(feats_kw).get("score", 0.0))
	assertions.assert_true(kw_score > plain_score, "friendly board keywords raise the score")


static func _test_reactive_potential(assertions) -> void:
	# reactive_potential = the largest set of Action/Reaction hand cards the AI can
	# pay for at once with its leftover ready runes (each rune = 1 energy or 1 power
	# of its domain). Validates affordability, domain matching, and the combination
	# check when more than one card is individually affordable.

	# No ready runes → cannot react.
	var s := _bare_snapshot(0)
	s["my_hand_reactive"] = [{"energy": 1, "power": []}]
	s["my_ready_rune_domains"] = []
	assertions.assert_eq(int(ScoreModelScript.build_score_features(s, s, []).get("reactive_potential", -1)), 0, "no ready runes means no reactive potential")

	# One card costing 1 energy + 1 fury power; two fury runes pay it (recycle one
	# for power, tap one for energy). Both runes are usable → none unusable.
	var s2 := _bare_snapshot(0)
	s2["my_hand_reactive"] = [{"energy": 1, "power": [{"domain": "fury", "amount": 1}]}]
	s2["my_ready_rune_domains"] = ["fury", "fury"]
	s2["my_ready_runes"] = 2
	var f2 := ScoreModelScript.build_score_features(s2, s2, [])
	assertions.assert_eq(int(f2.get("reactive_potential", -1)), 1, "fury+energy card payable by two fury runes")
	assertions.assert_eq(int(f2.get("unusable_runes", -1)), 0, "both runes consumed → none unusable")

	# Domain mismatch: a fury power cost cannot be paid by calm runes. Both calm
	# runes are dead weight → both unusable.
	var s3 := _bare_snapshot(0)
	s3["my_hand_reactive"] = [{"energy": 0, "power": [{"domain": "fury", "amount": 1}]}]
	s3["my_ready_rune_domains"] = ["calm", "calm"]
	s3["my_ready_runes"] = 2
	var f3 := ScoreModelScript.build_score_features(s3, s3, [])
	assertions.assert_eq(int(f3.get("reactive_potential", -1)), 0, "wrong-domain runes cannot pay a power cost")
	assertions.assert_eq(int(f3.get("unusable_runes", -1)), 2, "unpayable runes are all unusable")

	# Combination check: two 1-energy cards, two runes → both payable at once.
	var s4 := _bare_snapshot(0)
	s4["my_hand_reactive"] = [{"energy": 1, "power": []}, {"energy": 1, "power": []}]
	s4["my_ready_rune_domains"] = ["fury", "calm"]
	assertions.assert_eq(int(ScoreModelScript.build_score_features(s4, s4, []).get("reactive_potential", -1)), 2, "two cheap cards both payable with two runes")

	# Combination check: two 2-energy cards, only two runes → just one at a time,
	# but both runes are still consumable by that one card → none unusable.
	var s5 := _bare_snapshot(0)
	s5["my_hand_reactive"] = [{"energy": 2, "power": []}, {"energy": 2, "power": []}]
	s5["my_ready_rune_domains"] = ["fury", "calm"]
	s5["my_ready_runes"] = 2
	var f5 := ScoreModelScript.build_score_features(s5, s5, [])
	assertions.assert_eq(int(f5.get("reactive_potential", -1)), 1, "only one of two pricey cards payable at once")
	assertions.assert_eq(int(f5.get("unusable_runes", -1)), 0, "both runes consumable by the affordable card")

	# Excess runes beyond what any card needs are unusable: one cheap card, three
	# runes → one rune used, two dead.
	var s6 := _bare_snapshot(0)
	s6["my_hand_reactive"] = [{"energy": 1, "power": []}]
	s6["my_ready_rune_domains"] = ["fury", "calm", "body"]
	s6["my_ready_runes"] = 3
	var f6 := ScoreModelScript.build_score_features(s6, s6, [])
	assertions.assert_eq(int(f6.get("unusable_runes", -1)), 2, "runes beyond reactive need are unusable")


static func _bare_snapshot(ai_index: int) -> Dictionary:
	return {
		"ai_index": ai_index,
		"my_score": 0, "opp_score": 0, "victory_score": 8,
		"game_over": false, "winner_index": -1,
		"my_hand": 3, "opp_hand": 3,
		"my_energy": 0, "my_ready_runes": 0, "opp_ready_runes": 0,
		"my_unit_might": 0, "opp_unit_might": 0,
		"my_cards_played": 0, "my_cards_discarded": 0,
		"my_hand_reactive": [], "my_ready_rune_domains": [],
		"bf": {}, "bf_scored": [], "units": {},
	}


static func _unit(owner: int, location: String, might: int, keywords: Array) -> Dictionary:
	return {
		"owner": owner, "location": location, "might": might, "damage": 0,
		"exhausted": false, "stunned": false, "keywords": keywords,
	}


static func _test_line_steps_parallel_and_labeled(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {"node_budget": 80, "time_budget_ms": 1000, "beam_width": 6})
	var lines: Array = result.get("candidate_lines", [])
	assertions.assert_true(not lines.is_empty(), "search returns lines for step-structure check")
	var ok_lengths := true
	var ok_kinds := true
	var ok_intermediate_context := true
	var ok_pre_hashes := true
	for line in lines:
		var moves: Array = line.get("moves", [])
		var contexts: Array = line.get("move_contexts", [])
		var pre_hashes: Array = line.get("expected_pre_hashes", [])
		if moves.size() != contexts.size() or moves.size() != pre_hashes.size():
			ok_lengths = false
		for ctx in contexts:
			var kind := str(ctx.get("kind", ""))
			if kind != "scripted" and kind != "intermediate":
				ok_kinds = false
			# Every intermediate step must explain itself for the AI to read.
			if kind == "intermediate" and str(ctx.get("context", "")) == "":
				ok_intermediate_context = false
		for ph in pre_hashes:
			if str(ph) == "":
				ok_pre_hashes = false
	assertions.assert_true(ok_lengths, "moves, move_contexts, expected_pre_hashes are parallel")
	assertions.assert_true(ok_kinds, "every step kind is scripted or intermediate")
	assertions.assert_true(ok_intermediate_context, "every intermediate step carries a context label")
	assertions.assert_true(ok_pre_hashes, "every step has a non-empty pre_hash for divergence checks")


static func _test_reactive_search_in_showdown_window(assertions) -> void:
	# AI (index 0) holds showdown focus — a reactive response window. Reactive
	# search should plan responses (play action/reaction or pass) until the
	# showdown resolves, not fall back to main-phase planning.
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "SHOWDOWN_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"hand": ["void-seeker"],
				"pool": {"energy": 5, "power": {"fury": 1}},
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"deck_size": 5, "rune_deck_size": 12
			},
			{
				"battlefield-a": [{"id": "blazing-scorcher", "owner": 1}],
				"deck_size": 5, "rune_deck_size": 12
			}
		]
	})
	var gs = h.gs()
	gs.focus_player_index = 0
	gs.board.active_showdown_bf = 0
	var before := _hash(gs, 0)
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(gs, 0, {"mode": "reactive", "node_budget": 40, "time_budget_ms": 1000, "beam_width": 6})
	var stats: Dictionary = result.get("search_stats", {})
	assertions.assert_eq(str(stats.get("mode", "")), "reactive", "search reports reactive mode")
	var lines: Array = result.get("candidate_lines", [])
	assertions.assert_true(not lines.is_empty(), "reactive search returns at least one line")
	# A reactive line must start with a window move (pass or an action/reaction
	# play), never a main-phase move like "end turn" / "move ... to battlefield".
	var ok_first_step := true
	for line in lines:
		var moves: Array = line.get("moves", [])
		if moves.is_empty():
			ok_first_step = false
			continue
		var first := str(moves[0])
		if first == "end turn" or first.begins_with("move "):
			ok_first_step = false
	assertions.assert_true(ok_first_step, "reactive lines start with a window response (pass/play), not a main-phase move")
	assertions.assert_eq(_hash(gs, 0), before, "reactive search leaves live state unchanged")
