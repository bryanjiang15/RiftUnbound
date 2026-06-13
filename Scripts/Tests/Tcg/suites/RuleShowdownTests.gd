class_name RuleShowdownTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_showdown_establishes_control(assertions)
	_test_showdown_waits_for_pending_discard(assertions)
	_test_p2_can_act_after_showdown_focus_pass(assertions)


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


static func _test_showdown_waits_for_pending_discard(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "traveling-merchant", "exhausted": false}], "hand": ["fury-rune"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller.submit_command(0, "move traveling-merchant to battlefield-a")
	assertions.assert_eq(h.gs().pending_prompt.get("type", ""), "choose_discard",
		"move discard prompt is pending")
	assertions.assert_true(h.gs().board.staged_showdowns.size() > 0, "showdown is staged")
	assertions.assert_true(not h.gs().is_showdown_state(), "showdown waits for discard choice")


static func _test_p2_can_act_after_showdown_focus_pass(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "traveling-merchant", "exhausted": false}], "hand": ["fury-rune"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "move traveling-merchant to battlefield-a", ["fury-rune"])
	assertions.assert_true(h.gs().is_showdown_state(), "showdown begins after discard")
	h.cmd(0, "pass")
	assertions.assert_true(h.gs().can_player_act(1), "p2 can act when showdown focus passes")
	h.cmd(1, "pass")
	assertions.assert_true(not h.gs().is_showdown_state(), "showdown closes after both pass")
