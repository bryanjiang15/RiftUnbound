class_name RuleSimulationTests
extends RefCounted

# Phase 2.5 — engine-truth simulation. Verifies that GameState.clone() is a true
# deep copy (no aliasing) and that MoveSimulator computes outcomes on the clone
# WITHOUT ever mutating the live state.

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const MoveSimulatorScript = preload("res://Scripts/Game/MoveSimulator.gd")
const BriefStateSerializerScript = preload("res://Scripts/AI/BriefStateSerializer.gd")

static func run(assertions) -> void:
	_test_clone_is_independent(assertions)
	_test_simulate_does_not_mutate_live(assertions)
	_test_simulate_unopposed_move_conquers(assertions)
	_test_simulate_illegal_move_is_flagged(assertions)
	_test_presim_inlined_into_brief_state(assertions)


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

