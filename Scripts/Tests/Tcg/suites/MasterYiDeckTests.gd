class_name MasterYiDeckTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

# Scenario tests for the OGS Master Yi (Calm/Body) deck cards and the engine
# features added to support them.

static func run(assertions) -> void:
	_test_deck_validates(assertions)
	_test_runes_load(assertions)
	_test_meditative_passive_runes(assertions)
	_test_meditative_no_bonus_under_8(assertions)
	_test_wielder_alone_in_combat(assertions)
	_test_wielder_not_alone(assertions)
	_test_legend_aura_defending_alone(assertions)
	_test_stormclaw_channels_exhausted(assertions)
	_test_honed_enters_ready(assertions)
	_test_mobilize_channels_rune(assertions)
	_test_mobilize_draws_when_no_runes(assertions)
	_test_confront_units_enter_ready(assertions)
	_test_en_garde_alone_bonus(assertions)
	_test_en_garde_no_bonus_with_ally(assertions)
	_test_cannon_barrage_hits_combat(assertions)
	_test_fortified_position_shield(assertions)


static func _runes(rune_id: String, n: int) -> Array:
	var out: Array = []
	for _i in range(n):
		out.append({"id": rune_id, "exhausted": false})
	return out


static func _test_deck_validates(assertions) -> void:
	var data = DeckLoader.load_deck("res://Data/Decks/master-yi-calm-body.json")
	var errors = DeckLoader.validate(data)
	assertions.assert_true(errors.is_empty(), "master yi deck validates", str(errors))


static func _test_runes_load(assertions) -> void:
	var calm = CardLoader.get_card("calm-rune")
	var body = CardLoader.get_card("body-rune")
	assertions.assert_true(calm != null and body != null, "calm/body runes load")
	assertions.assert_true(
		calm != null and calm.domain.has("calm") and body != null and body.domain.has("body"),
		"rune domains are correct"
	)


static func _test_meditative_passive_runes(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"base": [{"id": "master-yi-meditative"}], "runes": _runes("body-rune", 8)},
			{},
		],
	})
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	var yi = h.find_unit("master-yi-meditative")
	assertions.assert_eq(yi.get_current_might(), 8, "meditative has +4 Might with 8 runes")


static func _test_meditative_no_bonus_under_8(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"base": [{"id": "master-yi-meditative"}], "runes": _runes("body-rune", 7)},
			{},
		],
	})
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	var yi = h.find_unit("master-yi-meditative")
	assertions.assert_eq(yi.get_current_might(), 4, "meditative has no bonus with 7 runes")


static func _test_wielder_alone_in_combat(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "wielder-of-water"}]},
			{},
		],
	})
	var w = h.find_unit("wielder-of-water")
	w.is_attacker = true
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	assertions.assert_eq(w.get_current_might(), 4, "wielder +2 attacking alone")


static func _test_wielder_not_alone(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "wielder-of-water"}, {"id": "stalwart-poro"}]},
			{},
		],
	})
	var w = h.find_unit("wielder-of-water")
	w.is_attacker = true
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	assertions.assert_eq(w.get_current_might(), 2, "wielder no bonus when not alone")


static func _test_legend_aura_defending_alone(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"legend": "master-yi-wuju-bladesman",
			 "battlefield-a": [{"id": "playful-phantom"}]},
			{},
		],
	})
	var p = h.find_unit("playful-phantom")
	p.is_defender = true
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	assertions.assert_eq(p.get_current_might(), 7, "legend aura +2 to lone defender")


static func _test_stormclaw_channels_exhausted(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"hand": ["stormclaw-ursine"], "pool": {"energy": 10}, "rune_deck_size": 12},
			{},
		],
	})
	h.cmd(0, "play stormclaw-ursine")
	var ps = h.gs().players[0]
	assertions.assert_eq(ps.channeled_runes.size(), 1, "stormclaw channels 1 rune on play")
	assertions.assert_true(
		ps.channeled_runes.size() == 1 and ps.channeled_runes[0].is_exhausted,
		"channeled rune enters exhausted"
	)


static func _test_honed_enters_ready(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"hand": ["master-yi-honed"], "pool": {"energy": 10, "power": {"body": 2}}},
			{},
		],
	})
	h.cmd(0, "play master-yi-honed")
	var honed = h.find_unit("master-yi-honed")
	assertions.assert_true(honed != null and not honed.is_exhausted, "honed enters ready")


static func _test_mobilize_channels_rune(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"hand": ["mobilize"], "pool": {"energy": 5}, "rune_deck_size": 5, "deck_size": 5},
			{"deck_size": 5},
		],
	})
	h.cmd(0, "play mobilize")
	var ps = h.gs().players[0]
	assertions.assert_eq(ps.channeled_runes.size(), 1, "mobilize channels a rune")
	assertions.assert_true(
		ps.channeled_runes.size() == 1 and ps.channeled_runes[0].is_exhausted,
		"mobilize channels the rune exhausted"
	)


static func _test_mobilize_draws_when_no_runes(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"hand": ["mobilize"], "pool": {"energy": 5}, "rune_deck_size": 0, "deck_size": 5},
			{"deck_size": 5},
		],
	})
	h.cmd(0, "play mobilize")
	var ps = h.gs().players[0]
	assertions.assert_eq(ps.channeled_runes.size(), 0, "mobilize channels nothing without runes")
	assertions.assert_eq(ps.hand.size(), 1, "mobilize draws 1 instead")


static func _test_confront_units_enter_ready(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"hand": ["confront", "stalwart-poro"], "pool": {"energy": 10}, "deck_size": 5},
			{"deck_size": 5},
		],
	})
	h.cmd(0, "play confront")
	assertions.assert_true(
		h.gs().players[0].units_enter_ready_this_turn, "confront sets enter-ready flag"
	)
	h.cmd(0, "play stalwart-poro")
	var poro = h.find_unit("stalwart-poro")
	assertions.assert_true(
		poro != null and not poro.is_exhausted, "unit enters ready after confront"
	)


static func _test_en_garde_alone_bonus(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "playful-phantom"}]},
			{},
		],
	})
	var p = h.find_unit("playful-phantom")
	var ab = CardLoader.get_card("en-garde").abilities[0]
	h.controller.ability_resolver.resolve_ability(ab, null, p, h.gs(), {})
	assertions.assert_eq(p.get_current_might(), 7, "en garde +2 to a lone unit")


static func _test_en_garde_no_bonus_with_ally(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "playful-phantom"}, {"id": "stalwart-poro"}]},
			{},
		],
	})
	var p = h.find_unit("playful-phantom")
	var ab = CardLoader.get_card("en-garde").abilities[0]
	h.controller.ability_resolver.resolve_ability(ab, null, p, h.gs(), {})
	assertions.assert_eq(p.get_current_might(), 6, "en garde +1 only when not alone")


static func _test_cannon_barrage_hits_combat(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{},
			{"battlefield-a": [{"id": "mountain-drake"}, {"id": "playful-phantom"}]},
		],
	})
	var gs = h.gs()
	gs.combat_bf_index = 0
	gs.attacker_player_index = 1
	var source = gs.players[0].legend  # owned by P0 (the caster)
	var ab = CardLoader.get_card("cannon-barrage").abilities[0]
	h.controller.ability_resolver.resolve_ability(ab, source, null, gs, {})
	var drake = h.find_unit("mountain-drake")
	var phantom = h.find_unit("playful-phantom")
	assertions.assert_true(
		drake != null and drake.damage == 2 and phantom != null and phantom.damage == 2,
		"cannon barrage deals 2 to all enemy units in combat"
	)


static func _test_fortified_position_shield(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "playful-phantom"}]},
			{},
		],
	})
	var p = h.find_unit("playful-phantom")
	var ab = CardLoader.get_card("fortified-position").abilities[0]
	h.controller.ability_resolver.resolve_ability(ab, null, p, h.gs(), {})
	p.is_defender = true
	assertions.assert_eq(p.get_current_might(), 7, "fortified position grants Shield 2")
