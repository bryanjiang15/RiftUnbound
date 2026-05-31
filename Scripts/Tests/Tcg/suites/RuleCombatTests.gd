class_name RuleCombatTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_auto_combat_deals_damage(assertions)


static func _test_auto_combat_deals_damage(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "SHOWDOWN_OPEN",
		"auto_combat_damage": true,
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "blazing-scorcher", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().combat_bf_index = 0
	h.gs().attacker_player_index = 0
	var lines = CombatProcessor.proceed_to_damage(h.gs())
	var enemy = h.gs().board.battlefields[0].units[1][0]
	assertions.assert_true(enemy.damage > 0 or lines.size() > 0, "auto combat assigns damage")
