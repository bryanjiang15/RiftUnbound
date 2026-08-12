class_name RuleAnalysisStateTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const AnalysisStateCodecScript = preload("res://Scripts/AI/AnalysisStateCodec.gd")
const ScoreModelScript = preload("res://Scripts/Game/ScoreModel.gd")
const TurnSearchScript = preload("res://Scripts/Game/TurnSearch.gd")


static func run(assertions) -> void:
	_test_round_trip_structural_hash(assertions)
	_test_duplicate_instances_and_mutable_fields(assertions)
	_test_unsupported_showdown_rejected(assertions)
	_test_winning_fixture_round_trip(assertions)
	_test_preserve_with_progress_search(assertions)


static func _hash(gs: GameState, seat: int = 0) -> String:
	return AnalysisStateCodecScript.root_hash(gs, seat)


static func _test_round_trip_structural_hash(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")
	var gs: GameState = h.gs()
	gs.players[0].rune_pool.energy = 3
	gs.players[0].rune_pool.power["fury"] = 2
	gs.board.battlefields[0].controller_index = 0
	var before := _hash(gs, 0)
	var payload: Dictionary = AnalysisStateCodecScript.export_state(gs)
	assertions.assert_eq(str(payload.get("schema_version", "")), AnalysisStateCodecScript.SCHEMA_VERSION, "export stamps schema version")
	assertions.assert_true(bool(payload.get("replay", {}).get("supported", false)), "main+neutral_open is replay-supported")
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(payload)
	assertions.assert_true(bool(restored.get("ok", false)), "restore ok")
	var gs2: GameState = restored["gs"]
	assertions.assert_eq(_hash(gs2, 0), before, "restore reproduces ScoreModel.structural_hash")
	assertions.assert_eq(gs2.players[0].rune_pool.energy, 3, "rune energy round-trips")
	assertions.assert_eq(int(gs2.players[0].rune_pool.power.get("fury", 0)), 2, "rune power round-trips")
	assertions.assert_eq(gs2.board.battlefields[0].controller_index, 0, "battlefield control round-trips")


static func _test_duplicate_instances_and_mutable_fields(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, 1],
		"players": [
			{
				"score": 3,
				"pool": {"energy": 1, "power": {"calm": 1}},
				"hand": ["chemtech-enforcer", "chemtech-enforcer"],
				"base": [{"id": "vi-destructive", "exhausted": true, "damage": 2}],
				"runes": [{"id": "fury-rune", "exhausted": true}, {"id": "fury-rune", "exhausted": false}],
				"deck_size": 4, "rune_deck_size": 8
			},
			{
				"score": 1,
				"battlefield-b": [{"id": "stalwart-poro", "owner": 1, "exhausted": false, "damage": 1}],
				"deck_size": 4, "rune_deck_size": 8
			}
		]
	})
	var gs: GameState = h.gs()
	var vi = gs.find_instance_anywhere("vi-destructive")
	assertions.assert_true(vi != null, "vi exists")
	vi.temp_might_bonus = 2
	vi.buff_counters = 1
	var hand_ids: Array = []
	for c in gs.players[0].hand:
		hand_ids.append(c.instance_id)
	assertions.assert_true("chemtech-enforcer" in hand_ids, "first copy keeps definition id")
	assertions.assert_true("chemtech-enforcer-2" in hand_ids, "duplicate gets -2 suffix")
	var before := _hash(gs, 0)
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(AnalysisStateCodecScript.export_state(gs))
	assertions.assert_true(bool(restored.get("ok", false)), "duplicate-id restore ok")
	var gs2: GameState = restored["gs"]
	assertions.assert_eq(_hash(gs2, 0), before, "mutable fields + duplicate ids round-trip hash")
	var vi2 = gs2.find_instance_anywhere("vi-destructive")
	assertions.assert_eq(vi2.damage, 2, "damage round-trips")
	assertions.assert_true(vi2.is_exhausted, "exhaustion round-trips")
	assertions.assert_eq(vi2.temp_might_bonus, 2, "temp might round-trips")
	assertions.assert_eq(vi2.buff_counters, 1, "buff counters round-trip")
	assertions.assert_eq(gs2.players[0].hand.size(), 2, "both hand copies restored")
	assertions.assert_eq(gs2.board.battlefields[1].controller_index, 1, "opp battlefield control round-trips")


static func _test_unsupported_showdown_rejected(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")
	var gs: GameState = h.gs()
	gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
	var replay: Dictionary = AnalysisStateCodecScript.replay_eligibility(gs)
	assertions.assert_true(not bool(replay.get("supported", true)), "showdown is unsupported for v1 replay")
	var payload: Dictionary = AnalysisStateCodecScript.export_state(gs)
	assertions.assert_true(not bool(payload.get("replay", {}).get("supported", true)), "export records unsupported replay")
	# Restore still works (hash check) but callers must not approximate unsupported states.
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(payload)
	assertions.assert_true(bool(restored.get("ok", false)), "unsupported states still restore for inspection")
	assertions.assert_true(not bool(restored.get("replay", {}).get("supported", true)), "restored replay flag stays unsupported")


static func _test_winning_fixture_round_trip(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/search_winning_line.json")
	var before := _hash(h.gs(), 0)
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(AnalysisStateCodecScript.export_state(h.gs()))
	assertions.assert_eq(_hash(restored["gs"], 0), before, "winning-line fixture round-trips")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(restored["gs"], 0, {"node_budget": 80, "time_budget_ms": 1000, "beam_width": 6})
	var lines: Array = result.get("candidate_lines", [])
	assertions.assert_true(not lines.is_empty(), "search on restored winning fixture returns lines")
	var best: Dictionary = lines[0]
	assertions.assert_true(best.get("resolved_state", {}).get("wins_game", false), "restored winning fixture still finds lethal")


static func _test_preserve_with_progress_search(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/preserve_with_progress.json")
	var gs: GameState = h.gs()
	assertions.assert_true(gs.find_instance_anywhere("vi-destructive") != null, "friendly vi is on board")
	var payload: Dictionary = AnalysisStateCodecScript.export_state(gs)
	var restored: Dictionary = AnalysisStateCodecScript.restore_state(payload)
	assertions.assert_eq(_hash(restored["gs"], 0), _hash(gs, 0), "preserve fixture round-trips")
	var searcher = TurnSearchScript.new()
	var result: Dictionary = searcher.search(restored["gs"], 0, {
		"node_budget": 120, "time_budget_ms": 1500, "beam_width": 8, "max_depth": 8, "top_n": 12
	})
	var lines: Array = result.get("candidate_lines", [])
	assertions.assert_true(not lines.is_empty(), "preserve fixture search returns lines")
	var found_progress := false
	for line in lines:
		var cmds: Array = line.get("moves", [])
		var pass_only := true
		for cmd in cmds:
			var s := str(cmd).strip_edges().to_lower()
			if s != "pass" and s != "end turn":
				pass_only = false
				break
		if pass_only:
			continue
		var leaf: Dictionary = line.get("search_state", {})
		var units: Dictionary = leaf.get("units", {})
		if units.has("vi-destructive") and str(cmds).find("move") >= 0:
			found_progress = true
			break
	assertions.assert_true(found_progress, "search finds a non-pass line that keeps vi")
