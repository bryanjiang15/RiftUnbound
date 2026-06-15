class_name RuleChainTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_spell_adds_to_chain(assertions)
	_test_neutral_closed_only_priority_player_acts(assertions)


static func _test_spell_adds_to_chain(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 5, "power": {}},
				"hand": ["void-seeker"],
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"battlefield-a": [{"id": "blazing-scorcher", "owner": 1}],
				"deck_size": 5,
				"rune_deck_size": 12
			},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play void-seeker", ["blazing-scorcher"])
	assertions.assert_no_error(h.controller, "void seeker plays without error")
	assertions.assert_true(h.gs().chain.is_empty(), "void seeker chain resolves")
	var enemy = h.gs().board.battlefields[0].units[1][0]
	assertions.assert_true(enemy.damage > 0, "void seeker deals damage to target")


static func _test_neutral_closed_only_priority_player_acts(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 5, "power": {}},
				"hand": ["void-seeker"],
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"battlefield-a": [{"id": "blazing-scorcher", "owner": 1}],
				"deck_size": 5,
				"rune_deck_size": 12
			},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller.submit_command(0, "play void-seeker target blazing-scorcher")
	assertions.assert_no_error(h.controller, "p1 plays spell onto chain")
	assertions.assert_eq(h.gs().current_state, TurnStateMachine.State.NEUTRAL_CLOSED,
		"neutral closed after spell")
	assertions.assert_false(h.gs().chain.is_empty(), "chain has pending item")
	assertions.assert_eq(h.gs().priority_player_index, 1, "priority passes to p2")
	assertions.assert_false(h.gs().can_player_act(0), "p1 cannot act without priority")
	assertions.assert_true(h.gs().can_player_act(1), "p2 has chain priority")

	h.controller.submit_command(0, "pass")
	assertions.assert_true(h.controller.last_command_error,
		"p1 cannot pass without chain priority")
