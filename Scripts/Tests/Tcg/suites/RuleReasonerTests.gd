class_name RuleReasonerTests
extends RefCounted

const HarnessScript = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const AIPlayerScript = preload("res://Scripts/AI/AIPlayer.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")


static func run(assertions) -> void:
	_test_canonical_reasoner_line_executes(assertions)
	_test_root_mismatch_rejected_before_step_zero(assertions)
	_test_hashless_reasoner_line_rejected(assertions)
	_test_turn8_two_point_continuation_discoverable(assertions)


static func _fixture():
	var h = HarnessScript.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_reorderable.json")
	h.gs().game_session_id = ""
	return h


static func _hash(gs: GameState) -> String:
	return ScoreModelScript.structural_hash(ScoreModelScript.snapshot(gs, 0))


static func _ai(h: TcgTestHarness):
	var ai = AIPlayerScript.new()
	ai.controller = h.controller
	ai.player_index = 0
	return ai


static func _emit(root_hash: String, include_hashes: bool = true) -> Dictionary:
	var line := {
		"line_id": "deepen-1-line-1-test",
		"moves": ["end turn"],
		"move_contexts": [{"kind": "scripted", "context": ""}],
		"expected_pre_hashes": ([root_hash] if include_hashes else []),
		"root_state_hash": root_hash,
		"legal": true,
		"complete": true,
		"terminal_reason": "end_turn",
		"search_mode": "main",
	}
	return {
		"kind": "line",
		"chosen_line_id": line["line_id"],
		"root_state_hash": root_hash,
		"committed_line": line,
	}


static func _test_canonical_reasoner_line_executes(assertions) -> void:
	var h = _fixture()
	var ai = _ai(h)
	var root := _hash(h.gs())
	var accepted: bool = ai._try_commit_reasoner_line(h.gs(), _emit(root))
	assertions.assert_true(accepted, "complete canonical reasoner line executes")
	assertions.assert_eq(h.gs().turn_player_index, 1, "step zero was submitted")
	ai.free()


static func _test_root_mismatch_rejected_before_step_zero(assertions) -> void:
	var h = _fixture()
	var ai = _ai(h)
	var before := _hash(h.gs())
	var accepted: bool = ai._try_commit_reasoner_line(h.gs(), _emit("stale-root"))
	assertions.assert_false(accepted, "stale reasoner root is rejected")
	assertions.assert_eq(_hash(h.gs()), before, "root rejection does not mutate the game")
	ai.free()


static func _test_hashless_reasoner_line_rejected(assertions) -> void:
	var h = _fixture()
	var ai = _ai(h)
	var root := _hash(h.gs())
	var accepted: bool = ai._try_commit_reasoner_line(
		h.gs(), _emit(root, false)
	)
	assertions.assert_false(accepted, "hashless invented reasoner line is rejected")
	assertions.assert_eq(_hash(h.gs()), root, "hashless rejection does not mutate the game")
	ai.free()


static func _test_turn8_two_point_continuation_discoverable(assertions) -> void:
	var h = HarnessScript.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/reasoner_turn8_two_point.json")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(h.gs(), 0, {
		"mode": "main",
		"max_depth": 12,
		"node_budget": 300,
		"time_budget_ms": 1000,
		"beam_width": 8,
	})
	var found := false
	for line in result.get("candidate_lines", []):
		if int(line.get("resolved_state", {}).get("my_score_after", 0)) >= 4:
			found = true
			break
	assertions.assert_true(found,
		"Turn 8 regression search finds the multi-action two-point continuation")
