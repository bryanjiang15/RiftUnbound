class_name RuleChainTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")

static func run(assertions) -> void:
	_test_spell_adds_to_chain(assertions)
	_test_neutral_closed_only_priority_player_acts(assertions)
	_test_deferred_target_resolves_duplicate_instance_id(assertions)
	_test_battlefield_same_card_instance_ids_are_globally_unique(assertions)


# Game-wide instance ids prevent cross-player collisions when the same card appears
# on both players' bases/battlefields (BUG-014 / GitHub #27).
static func _test_deferred_target_resolves_duplicate_instance_id(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"hand": ["void-seeker"],
				"pool": {"energy": 5, "power": {"fury": 1}},
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"base": [{"id": "chemtech-enforcer"}, {"id": "chemtech-enforcer"}],
				"deck_size": 5, "rune_deck_size": 12
			},
			{
				"base": [{"id": "chemtech-enforcer"}],
				"battlefield-b": [{"id": "chemtech-enforcer", "owner": 1}],
				"deck_size": 5, "rune_deck_size": 12
			}
		]
	})
	var gs = h.gs()
	var p1_base: Array = gs.players[0].base_permanents
	var p1_ally: CardInstance = p1_base[0]
	var p1_duplicate: CardInstance = p1_base[1]
	var enemy = gs.board.battlefields[1].units[1][0]
	assertions.assert_ne(p1_duplicate.instance_id, enemy.instance_id,
		"P1 duplicate and enemy copy have distinct game-wide ids")
	h.controller.submit_command(0, "play void-seeker")
	h.controller.submit_command(0, "choose %s" % enemy.instance_id)
	h.controller.submit_command(1, "pass")
	h.controller.submit_command(0, "pass")
	assertions.assert_no_error(h.controller, "void seeker targets enemy id without error")
	assertions.assert_true(p1_ally.damage == 0 and p1_duplicate.damage == 0,
		"P1 units are not damaged when enemy copy is targeted")
	assertions.assert_true(enemy.has_lethal_damage() or not enemy in gs.all_units_on_board(),
		"enemy unit receives void seeker damage")


# When both players field the same card, ids must stay unique so targeting is unambiguous
# (BUG-015 / GitHub #29).
static func _test_battlefield_same_card_instance_ids_are_globally_unique(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"hand": ["void-seeker"],
				"pool": {"energy": 5, "power": {"fury": 1}},
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"deck_size": 5, "rune_deck_size": 12
			},
			{
				"deck_size": 5, "rune_deck_size": 12
			}
		]
	})
	var gs = h.gs()
	var p1_unit = gs.players[0].create_instance(CardLoader.get_card("chemtech-enforcer"))
	var p2_unit = gs.players[1].create_instance(CardLoader.get_card("chemtech-enforcer"))
	gs.board.add_unit_to_battlefield(p1_unit, 0)
	gs.board.add_unit_to_battlefield(p2_unit, 0)
	assertions.assert_ne(p1_unit.instance_id, p2_unit.instance_id,
		"contested battlefield units get distinct instance ids")
	h.controller.submit_command(0, "play void-seeker")
	h.controller.submit_command(0, "choose %s" % p2_unit.instance_id)
	h.controller.submit_command(1, "pass")
	h.controller.submit_command(0, "pass")
	assertions.assert_no_error(h.controller, "void seeker can target enemy by unique id")
	assertions.assert_eq(p1_unit.damage, 0, "friendly unit is not damaged")
	assertions.assert_true(
		p2_unit.has_lethal_damage() or not p2_unit in gs.all_units_on_board(),
		"enemy unit is killed by void seeker"
	)


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
