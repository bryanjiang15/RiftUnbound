class_name RuleChainTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_spell_adds_to_chain(assertions)


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
