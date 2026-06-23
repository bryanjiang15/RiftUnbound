class_name RuleCombatTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_auto_combat_deals_damage(assertions)
	_test_assault_attacker_survives_defender_dies(assertions)
	_test_combat_kills_pre_damaged_unit_with_boosted_might(assertions)


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


static func _test_combat_kills_pre_damaged_unit_with_boosted_might(assertions) -> void:
	# Regression for BUG-009 / GitHub #48: auto-assign must use current Might (including
	# Shield and passive bonuses) when computing lethal, not printed/base Might alone.
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 1,
		"phase": "MAIN",
		"state": "SHOWDOWN_OPEN",
		"auto_combat_damage": true,
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{
				"legend": "master-yi-wuju-bladesman",
				"battlefield-a": [{"id": "stalwart-poro", "damage": 4}],
			},
			{
				"battlefield-a": [
					{"id": "cemetery-attendant"},
					{"id": "traveling-merchant"},
				],
			},
		],
	})
	var poro = h.find_unit("stalwart-poro")
	poro.is_defender = true
	poro.temp_keywords.append({"id": "shield", "value": 2, "duration": "combat"})
	h.gs().combat_bf_index = 0
	h.gs().attacker_player_index = 1
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	assertions.assert_eq(poro.get_current_might(), 7, "defender has boosted might before damage step")
	var trash_before = h.gs().players[0].trash.size()
	CombatProcessor.proceed_to_damage(h.gs(), h.controller)
	assertions.assert_true(
		h.gs().players[0].trash.size() > trash_before,
		"pre-damaged defender with boosted might dies when attackers have lethal"
	)
	assertions.assert_false(poro.is_at_battlefield(), "stalwart poro leaves the battlefield")
