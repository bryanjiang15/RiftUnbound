class_name RuleShowdownTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_showdown_establishes_control(assertions)


static func _test_showdown_establishes_control(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "vi-destructive", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().board.active_showdown_bf = 0
	var lines = ShowdownProcessor.close_showdown(h.gs())
	assertions.assert_eq(h.gs().board.battlefields[0].controller_index, 0, "showdown establishes control")
