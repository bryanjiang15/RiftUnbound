class_name RuleResourcesTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_tap_adds_energy(assertions)
	_test_accelerate_auto_recycles_rune(assertions)
	_test_on_discard_power_auto_recycles_rune(assertions)


static func _test_tap_adds_energy(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/resources_tap_rune.json")
	h.cmd(0, "tap rune-0")
	assertions.assert_eq(h.gs().players[0].rune_pool.energy, 1, "tap adds 1 energy")
	assertions.assert_no_error(h.controller, "tap rune succeeds")


# BUG-001: power costs must auto-recycle channeled runes when the pool is short.
static func _test_accelerate_auto_recycles_rune(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 6, "power": {}}, "hand": ["blazing-scorcher"],
			 "runes": [{"id": "fury-rune", "exhausted": false}],
			 "deck_size": 10, "rune_deck_size": 12},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var ps = h.gs().players[0]
	var rune_deck_before = ps.rune_deck.size()
	assertions.assert_eq(ps.channeled_runes.size(), 1, "fixture has one channeled rune")
	h.set_choices(["no"])
	h.cmd(0, "play blazing-scorcher accelerate")
	assertions.assert_no_error(h.controller, "accelerate play succeeds without manual recycle")
	assertions.assert_log_contains(h.controller, "[Auto] Rune recycled", "accelerate auto-recycles fury rune")
	assertions.assert_eq(ps.channeled_runes.size(), 0, "channeled rune moved off board")
	assertions.assert_eq(ps.rune_deck.size(), rune_deck_before + 1, "recycled rune returned to rune deck")
	var unit = h.find_unit("blazing-scorcher")
	assertions.assert_true(unit != null and not unit.is_exhausted, "accelerate enters ready")


static func _test_on_discard_power_auto_recycles_rune(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}},
			 "hand": ["chemtech-enforcer", "flame-chompers", "void-seeker"],
			 "runes": [{"id": "fury-rune", "exhausted": false}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var ps = h.gs().players[0]
	var rune_deck_before = ps.rune_deck.size()
	h.cmd_with_choices(0, "play chemtech-enforcer", ["flame-chompers", "yes"])
	assertions.assert_no_error(h.controller, "flame chompers optional play succeeds")
	assertions.assert_log_contains(h.controller, "[Auto] Rune recycled", "on_discard power auto-recycles fury rune")
	assertions.assert_eq(ps.channeled_runes.size(), 0, "channeled rune recycled for discard trigger cost")
	assertions.assert_eq(ps.rune_deck.size(), rune_deck_before + 1, "recycled rune returned to rune deck")
	assertions.assert_true(h.find_unit("flame-chompers") != null, "flame chompers played from discard")
