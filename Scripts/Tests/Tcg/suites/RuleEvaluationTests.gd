class_name RuleEvaluationTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")
const BriefStateSerializerScript = preload("res://Scripts/AI/BriefStateSerializer.gd")
const AIPlayerScript = preload("res://Scripts/AI/AIPlayer.gd")


static func run(assertions) -> void:
	_test_eval_fixture_loads_and_serializes(assertions)
	_test_eval_search_non_mutation(assertions)
	_test_eval_winning_line_discoverable(assertions)
	_test_eval_end_turn_commit(assertions)
	_test_eval_jinx_fixture_exists(assertions)


static func _hash(gs: GameState, seat: int) -> String:
	return ScoreModelScript.structural_hash(ScoreModelScript.snapshot(gs, seat))


static func _test_eval_fixture_loads_and_serializes(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_reorderable.json")
	var brief: Dictionary = BriefStateSerializerScript.serialize(h.gs(), 0)
	assertions.assert_eq(str(brief.get("decision_type", "")), "main_phase",
		"eval fixture serializes as main_phase")
	assertions.assert_true(brief.has("legal_moves"), "brief state includes legal moves")
	assertions.assert_true(brief.has("schema_version"), "brief state includes schema_version")


static func _test_eval_search_non_mutation(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")
	var before := _hash(h.gs(), 0)
	var searcher = TurnSearchScript.new()
	var _result: Dictionary = searcher.search(h.gs(), 0, {
		"node_budget": 40,
		"time_budget_ms": 500,
	})
	assertions.assert_eq(_hash(h.gs(), 0), before, "eval search leaves live state unchanged")


static func _test_eval_winning_line_discoverable(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {
		"node_budget": 80,
		"time_budget_ms": 1000,
		"beam_width": 6,
	})
	var found := false
	for line in result.get("candidate_lines", []):
		if bool(line.get("resolved_state", {}).get("wins_game", false)):
			found = true
			break
	assertions.assert_true(found, "eval winning-line fixture still finds a win")


static func _test_eval_end_turn_commit(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_reorderable.json")
	var root := _hash(h.gs(), 0)
	var ai = AIPlayerScript.new()
	ai.controller = h.controller
	ai.player_index = 0
	var line := {
		"line_id": "eval-end-turn",
		"moves": ["end turn"],
		"move_contexts": [{"kind": "scripted", "context": ""}],
		"expected_pre_hashes": [root],
		"root_state_hash": root,
		"legal": true,
		"complete": true,
		"terminal_reason": "end_turn",
		"search_mode": "main",
	}
	var accepted: bool = ai._try_commit_reasoner_line(h.gs(), {
		"kind": "line",
		"chosen_line_id": line["line_id"],
		"root_state_hash": root,
		"committed_line": line,
	})
	assertions.assert_true(accepted, "eval end-turn commit accepted")
	assertions.assert_eq(h.gs().turn_player_index, 1, "eval end-turn advances turn player")
	ai.free()


static func _test_eval_jinx_fixture_exists(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/eval_jinx_auto_discard.json")
	assertions.assert_eq(h.gs().players[0].hand.size(), 4, "jinx eval fixture has 4 hand cards")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {
		"seed_moves": ["play jinx-demolitionist"],
		"node_budget": 80,
		"time_budget_ms": 1000,
		"beam_width": 8,
		"max_depth": 8,
		"top_n": 8,
	})
	assertions.assert_true(not result.get("candidate_lines", []).is_empty(),
		"jinx seeded search returns candidates")
