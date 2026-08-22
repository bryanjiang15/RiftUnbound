class_name RuleSimulationTests
extends RefCounted

# Phase 2.5 — engine-truth simulation. Verifies that GameState.clone() is a true
# deep copy (no aliasing) and that MoveSimulator computes outcomes on the clone
# WITHOUT ever mutating the live state.

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const BriefStateSerializerScript = preload("res://Scripts/AI/BriefStateSerializer.gd")
const LineRiskProbeScript = preload("res://Scripts/Game/LineRiskProbe.gd")

static func run(assertions) -> void:
	_test_clone_is_independent(assertions)
	_test_clone_remaps_pending_chain_item(assertions)
	_test_clone_strips_freed_controller_from_prompt(assertions)
	_test_simulate_does_not_mutate_live(assertions)
	_test_simulate_unopposed_move_conquers(assertions)
	_test_simulate_illegal_move_is_flagged(assertions)
	_test_presim_inlined_into_brief_state(assertions)
	_test_resolved_state_controllers_after_and_unit_presence(assertions)
	_test_resolved_state_play_to_base_lists_unit_in_base(assertions)
	_test_line_risk_probe_smoke(assertions)


# A structural signature of the decision-relevant state. Two states with the same
# signature are equal for our purposes; a clone must match the live signature and
# stay matched after the live state is mutated independently.
static func _signature(gs: GameState) -> String:
	var parts: Array[String] = []
	for i in range(gs.players.size()):
		var ps: PlayerState = gs.players[i]
		parts.append("P%d:score=%d:hand=%d:base=%d" % [
			i, ps.score, ps.hand.size(), ps.base_permanents.size()
		])
	for bf in gs.board.battlefields:
		parts.append("%s:ctrl=%d:u0=%d:u1=%d" % [
			bf.battlefield_id, bf.controller_index, bf.units[0].size(), bf.units[1].size()
		])
	for u in gs.all_units_on_board():
		parts.append("%s@%s:dmg=%d" % [u.instance_id, u.location, u.damage])
	parts.sort()
	return "|".join(parts)


static func _load(h) -> void:
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")


static func _test_clone_is_independent(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var sig_before := _signature(live)
	var clone: GameState = live.clone()

	assertions.assert_eq(_signature(clone), sig_before, "clone matches live signature")

	# Mutating the clone must not touch the live state (no shared CardInstances).
	var clone_unit: CardInstance = clone.players[0].base_permanents[0]
	clone_unit.damage += 5
	clone.players[0].score = 7
	clone.board.battlefields[0].controller_index = 0

	assertions.assert_eq(_signature(live), sig_before, "live unchanged after clone mutated")
	assertions.assert_true(
		live.players[0].base_permanents[0].damage == 0,
		"live unit damage not aliased to clone"
	)
	# And the original card object is a different instance from the clone's.
	assertions.assert_true(
		live.players[0].base_permanents[0] != clone_unit,
		"clone holds distinct CardInstance objects"
	)


static func _test_clone_remaps_pending_chain_item(assertions) -> void:
	# Falling Star locks the first target then prompts for the second. The
	# pending_prompt holds the ChainItem. Clone must remap that item (and its
	# first target) onto the cloned board, or the second choose damages a
	# different object and the visible unit only takes 3.
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {"fury": 2}}, "hand": ["falling-star"], "deck_size": 5, "rune_deck_size": 12},
			{"base": [{"id": "magma-wurm"}], "deck_size": 5, "rune_deck_size": 12},
		],
	})
	h.controller.submit_command(0, "play falling-star target magma-wurm")
	var live: GameState = h.gs()
	assertions.assert_true(not live.pending_prompt.is_empty(),
		"second Falling Star target is pending")
	var live_item: ChainItem = live.pending_prompt.get("chain_item")
	assertions.assert_true(live_item != null, "pending prompt holds a chain item")
	var live_wurm: CardInstance = live.find_instance_anywhere("magma-wurm")
	assertions.assert_true(live_item.targets.size() >= 1 and live_item.targets[0] == live_wurm,
		"first target is the live magma-wurm")

	var cloned: GameState = live.clone()
	var clone_item: ChainItem = cloned.pending_prompt.get("chain_item")
	var clone_wurm: CardInstance = cloned.find_instance_anywhere("magma-wurm")
	assertions.assert_true(clone_item != null, "cloned prompt still holds a chain item")
	assertions.assert_true(clone_item != live_item, "cloned chain item is not aliased")
	assertions.assert_true(clone_wurm != live_wurm, "cloned magma-wurm is not aliased")
	assertions.assert_true(clone_item.targets.size() >= 1 and clone_item.targets[0] == clone_wurm,
		"first target remaps onto the cloned magma-wurm")


static func _test_clone_strips_freed_controller_from_prompt(assertions) -> void:
	# Optional-ability prompts stash ctx.controller (a Node). Search/rollout
	# frees that controller, then until-turn-N clones the frontier state again.
	# `x is CardInstance` on the freed Node must not throw.
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	live.pending_prompt = {
		"player_index": 0,
		"type": "choose_optional",
		"valid_choices": ["yes", "no"],
		"source": live.players[0].base_permanents[0],
		"ctx": {
			"controller": h.controller,
			"player_index": 0,
			"target": live.players[0].base_permanents[0],
		},
		"prompt": "[PROMPT] test",
	}
	var cloned: GameState = live.clone()
	assertions.assert_true(cloned.pending_prompt.get("ctx", {}).get("controller") == null,
		"clone drops GameController from pending prompt ctx")
	var clone_src: CardInstance = cloned.pending_prompt.get("source")
	assertions.assert_true(clone_src != null and clone_src != live.players[0].base_permanents[0],
		"prompt source remaps onto the cloned card")
	h.controller.free()
	h.controller = null
	var cloned2: GameState = cloned.clone()
	assertions.assert_true(cloned2 != null, "second clone after controller free succeeds")
	assertions.assert_eq(str(cloned2.pending_prompt.get("type", "")), "choose_optional",
		"prompt type survives a clone after the original controller was freed")


static func _test_simulate_does_not_mutate_live(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var sig_before := _signature(live)

	var sim = MoveSimulatorScript.new()
	var _result = sim.simulate_move(live, 0, "move vi-destructive to battlefield-a")

	assertions.assert_eq(_signature(live), sig_before, "simulate_move leaves live state unchanged")


static func _test_simulate_unopposed_move_conquers(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()

	var sim = MoveSimulatorScript.new()
	var result: Dictionary = sim.simulate_move(live, 0, "move vi-destructive to battlefield-a")

	assertions.assert_true(result.get("legal", false), "unopposed move is legal in sim")
	var resolved: Dictionary = result.get("resolved_if_unanswered", {})
	assertions.assert_true(
		resolved.get("conquer", false),
		"sim reports conquer for unopposed move into uncontrolled battlefield"
	)


static func _test_simulate_illegal_move_is_flagged(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()

	var sim = MoveSimulatorScript.new()
	# No such unit "ghost" — the move is illegal and must be reported, not faked.
	var result: Dictionary = sim.simulate_move(live, 0, "move ghost to battlefield-a")

	assertions.assert_false(result.get("legal", true), "illegal move reported as not legal")


# Option-C wiring: BriefStateSerializer must inline engine-truth sims for the
# legal moves, keyed by the exact command string, without mutating live state.
static func _test_presim_inlined_into_brief_state(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var live: GameState = h.gs()
	var sig_before := _signature(live)

	var brief: Dictionary = BriefStateSerializerScript.serialize(live, 0)
	var sims: Dictionary = brief.get("move_simulations", {})

	assertions.assert_true(
		sims.has("move vi-destructive to battlefield-a"),
		"brief inlines a sim for the legal move"
	)
	assertions.assert_false(
		sims.has("end turn"),
		"trivial moves are skipped in pre-sim"
	)
	var conquered: bool = sims.get("move vi-destructive to battlefield-a", {}) \
		.get("resolved_if_unanswered", {}).get("conquer", false)
	assertions.assert_true(conquered, "inlined sim reports the conquer fact")
	assertions.assert_eq(_signature(live), sig_before, "serialize+presim leaves live state unchanged")


static func _test_resolved_state_controllers_after_and_unit_presence(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var sim = MoveSimulatorScript.new()
	var result: Dictionary = sim.simulate_move(h.gs(), 0, "move vi-destructive to battlefield-a")
	var resolved: Dictionary = result.get("resolved_if_unanswered", {})
	var controllers: Dictionary = resolved.get("controllers_after", {})
	assertions.assert_true(controllers.has("battlefield-a"), "controllers_after lists battlefield-a")
	assertions.assert_true(controllers.has("battlefield-b"), "controllers_after lists every battlefield")
	assertions.assert_eq(str(controllers.get("battlefield-a", "")), "me",
		"controllers_after shows me controlling the conquered field")
	assertions.assert_eq(str(controllers.get("battlefield-b", "")), "neutral",
		"unchanged battlefield still appears in controllers_after")
	assertions.assert_false(resolved.has("my_units_surviving"),
		"legacy my_units_surviving key is not emitted")
	var on_bf: Array = resolved.get("my_units_on_battlefields", [])
	assertions.assert_true(on_bf.has("vi-destructive"),
		"deployed unit is listed under my_units_on_battlefields")


static func _test_resolved_state_play_to_base_lists_unit_in_base(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 5, "power": {}},
				"hand": ["watchful-sentry"],
				"base": [],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12},
		],
	})
	var sim = MoveSimulatorScript.new()
	var result: Dictionary = sim.simulate_move(h.gs(), 0, "play watchful-sentry")
	assertions.assert_true(result.get("legal", false), "play unit to base is legal")
	var resolved: Dictionary = result.get("resolved_if_unanswered", {})
	var in_base: Array = resolved.get("my_units_in_base", [])
	assertions.assert_true(not in_base.is_empty(), "play-to-base emits my_units_in_base")
	var found := false
	for uid in in_base:
		if str(uid).begins_with("watchful-sentry"):
			found = true
			break
	assertions.assert_true(found, "played unit instance appears in my_units_in_base")
	assertions.assert_false(resolved.has("my_units_on_battlefields"),
		"unit played to base is not listed on battlefields")


static func _test_line_risk_probe_smoke(assertions) -> void:
	var h = TcgTestHarness.new()
	_load(h)
	var searcher = preload("res://Scripts/Game/TurnSearch.gd").new()
	var result: Dictionary = searcher.search(h.gs(), 0, {
		"mode": "main", "top_n": 2, "node_budget": 60, "time_budget_ms": 200, "max_depth": 6
	})
	var lines: Array = result.get("candidate_lines", [])
	assertions.assert_true(not lines.is_empty(), "turn search produced candidate lines")
	var probe = LineRiskProbeScript.new()
	var annotated: Array = probe.annotate_lines(h.gs(), 0, lines, {"budget_ms": 120})
	assertions.assert_eq(annotated.size(), lines.size(), "risk probe preserves line count")
	if not annotated.is_empty():
		var line0: Dictionary = annotated[0]
		assertions.assert_true(line0.has("risk"), "annotated line carries risk payload")

