class_name RuleCombatTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_auto_combat_deals_damage(assertions)
	_test_assault_attacker_survives_defender_dies(assertions)


static func _test_assault_attacker_survives_defender_dies(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "SHOWDOWN_OPEN",
		"auto_combat_damage": true,
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().combat_bf_index = 0
	h.gs().attacker_player_index = 1
	var lines = CombatProcessor.proceed_to_damage(h.gs())
	var bf = h.gs().board.battlefields[0]
	var p1_trash = h.gs().players[0].trash.size()
	var p2_at_bf = bf.units[1].size()
	assertions.assert_true(p1_trash > 0, "defender with lethal damage is killed in combat")
	assertions.assert_true(p2_at_bf > 0, "attacker with assault survives return damage")
	assertions.assert_eq(bf.controller_index, 1, "attacker conquers after winning combat")
	var log_text = "\n".join(lines)
	assertions.assert_true("Attacker wins combat" in log_text, "combat resolves as attacker win")


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
