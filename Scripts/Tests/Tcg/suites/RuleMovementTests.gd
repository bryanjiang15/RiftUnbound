class_name RuleMovementTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_move_exhausts_unit(assertions)
	_test_cannot_move_exhausted(assertions)


static func _test_move_exhausts_unit(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/movement_base_to_bf.json")
	var unit = h.gs().players[0].get_units_at_base()[0]
	h.cmd(0, "move vi-destructive to battlefield-a")
	assertions.assert_true(unit.is_exhausted, "move exhausts unit")
	assertions.assert_no_error(h.controller, "move to battlefield succeeds")


static func _test_cannot_move_exhausted(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "vi-destructive", "exhausted": true}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "move vi-destructive to battlefield-a")
	assertions.assert_true(h.controller.last_command_error, "exhausted unit cannot move")
