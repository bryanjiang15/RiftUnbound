class_name RuleCleanupTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_lethal_damage_kills(assertions)
	_test_deathknell_fires(assertions)


static func _test_lethal_damage_kills(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "chemtech-enforcer", "damage": 5}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var trash_before = h.gs().players[0].trash.size()
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	assertions.assert_true(h.gs().players[0].trash.size() > trash_before, "lethal damage kills unit")


static func _test_deathknell_fires(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "undercover-agent", "damage": 6}], "deck_size": 5, "rune_deck_size": 12, "hand": ["fury-rune", "fury-rune"]},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	assertions.assert_log_contains(h.controller, "Deathknell", "deathknell triggers on lethal")
