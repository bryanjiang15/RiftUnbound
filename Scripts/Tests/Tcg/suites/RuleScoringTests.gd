class_name RuleScoringTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_hold_scoring(assertions)
	_test_winning_point_draws_instead(assertions)


static func _test_hold_scoring(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 1,
		"turn_number": 2,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [-1, 1],
		"players": [
			{"score": 1, "deck_size": 5, "rune_deck_size": 12},
			{"score": 2, "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller._execute_start_of_turn()
	assertions.assert_score(h.gs(), 1, 3, "hold awards 1 point for controlled battlefield")


static func _test_winning_point_draws_instead(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/winning_point_conquer.json")
	var hand_before = h.gs().players[0].hand.size()
	var lines = ShowdownProcessor.establish_control(h.gs(), 0, 0, true, h.controller)
	assertions.assert_eq(h.gs().players[0].score, 7, "winning point conquer does not award 8th point")
	assertions.assert_true(h.gs().players[0].hand.size() > hand_before or lines.size() > 0, "winning point triggers draw instead")
