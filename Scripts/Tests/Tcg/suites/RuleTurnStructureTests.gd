class_name RuleTurnStructureTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_legend_draw_on_low_hand(assertions)
	_test_legend_draw_only_on_controller_turn(assertions)
	_test_end_turn_heals(assertions)


static func _test_legend_draw_on_low_hand(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/legend_draw.json")
	var hand_before = h.gs().players[0].hand.size()
	h.controller._execute_start_of_turn()
	var hand_after = h.gs().players[0].hand.size()
	assertions.assert_true(hand_after > hand_before, "legend draws when hand size <= 1 at beginning phase")


static func _test_legend_draw_only_on_controller_turn(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 1,
		"turn_number": 2,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"players": [
			{"hand": ["void-seeker"], "deck_size": 5, "rune_deck_size": 12},
			{"hand": ["void-seeker", "fury-rune"], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var p1_hand_before = h.gs().players[0].hand.size()
	var p2_hand_before = h.gs().players[1].hand.size()
	h.controller._execute_start_of_turn()
	assertions.assert_eq(
		h.gs().players[0].hand.size(),
		p1_hand_before,
		"p1 legend does not draw on p2 beginning phase",
	)
	assertions.assert_eq(
		h.gs().players[1].hand.size(),
		p2_hand_before + 1,
		"p2 gets only the normal draw when active player has more than one card",
	)


static func _test_end_turn_heals(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"turn_number": 1,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"score": 0, "base": [{"id": "chemtech-enforcer", "damage": 2}], "deck_size": 5, "rune_deck_size": 12},
			{"score": 0, "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var unit = h.gs().players[0].get_units_at_base()[0]
	h.cmd(0, "end turn")
	assertions.assert_eq(unit.damage, 0, "end turn heals units")
