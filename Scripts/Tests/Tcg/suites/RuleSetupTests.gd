class_name RuleSetupTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_deck_validation(assertions)
	_test_starter_deck_valid(assertions)


static func _test_deck_validation(assertions) -> void:
	var data = DeckLoader.load_deck("res://Data/Decks/starter-deck-p1.json")
	var errors = DeckLoader.validate(data)
	assertions.assert_true(errors.is_empty(), "starter deck p1 validates", str(errors))


static func _test_starter_deck_valid(assertions) -> void:
	var h = TcgTestHarness.new()
	h.setup()
	h.controller.start_game_from_config({
		"seed": 42,
		"battlefields": ["zaun-warrens", "targons-peak"],
		"first_player": 0,
	})
	assertions.assert_eq(h.gs().players.size(), 2, "setup creates two players")
	assertions.assert_eq(h.gs().board.battlefields.size(), 2, "setup creates two battlefields")
