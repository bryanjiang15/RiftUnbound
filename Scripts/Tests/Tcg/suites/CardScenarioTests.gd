class_name CardScenarioTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const TargetResolver = preload("res://Scripts/Game/TargetResolver.gd")

# Data-driven smoke tests for starter-deck card abilities.

static func run(assertions) -> void:
	_test_magma_wurm_aura(assertions)
	_test_meditation_exhaust_draws_two(assertions)
	_test_meditation_decline_draws_one(assertions)
	_test_meditation_no_ready_friendly_draws_one(assertions)
	_test_highlander_replaces_next_death(assertions)
	_test_highlander_expires_end_of_turn(assertions)
	_test_reavers_row_choose_defender(assertions)
	_test_fortified_position_choose_defender(assertions)
	_test_traveling_merchant_on_move(assertions)
	_test_traveling_merchant_on_move_to_base(assertions)
	_test_traveling_merchant_not_on_other_move(assertions)
	_test_scrapheap_on_play(assertions)
	_test_rhasa_cost_reduction(assertions)
	_test_gust_might_filter(assertions)
	_test_gust_rechecks_might_on_resolution(assertions)
	_test_fight_or_flight_move_base(assertions)
	_test_gentlemens_duel_applies_buffed_fight_damage(assertions)
	_test_brazen_buccaneer_discount(assertions)
	_test_cemetery_attendant(assertions)
	_test_get_excited(assertions)
	_test_reaction_spell_playable_in_neutral_open(assertions)
	_test_jinx_demolitionist_discard(assertions)
	_test_vi_recycle_cost(assertions)
	_test_raging_soul_keywords(assertions)
	_test_zaun_warrens_conquer(assertions)
	_test_targons_peak_ready_runes(assertions)
	_test_fading_memories_temporary(assertions)
	_test_undercover_agent_deathknell(assertions)
	_test_chemtech_discards_once(assertions)
	_test_blazing_scorcher_discard_no_prompt(assertions)
	_test_flame_chompers_discard_prompts(assertions)
	_test_flame_chompers_not_on_other_discard(assertions)
	_test_scrapheap_on_discard_effect(assertions)
	_test_p2_can_act_after_chemtech_scrapheap_turn(assertions)
	_test_gust_rejects_target_above_might(assertions)
	_test_play_targeted_spell_enumerates_targets(assertions)
	_test_ravenbloom_student_spell_trigger(assertions)
	_test_darius_second_card_trigger(assertions)
	_test_kaisa_debuff_minimum(assertions)
	_test_falling_star_can_repeat_target(assertions)
	_test_falling_star_requires_fury_power(assertions)
	_test_noxus_hopeful_legion_cost(assertions)
	_test_sprite_mother_token_here_temporary(assertions)
	_test_dr_mundo_trash_might_and_recycle(assertions)
	_test_retreat_returns_and_channels(assertions)
	_test_zhonya_sacrifices_gear_on_lethal(assertions)
	_test_unyielding_prevents_spell_damage(assertions)
	_test_defy_cost_filter(assertions)
	_test_find_your_center_cost_reduction(assertions)
	_test_pit_rookie_buffs_other(assertions)
	_test_grove_hold_draw(assertions)
	_test_vilemaw_blocks_move_to_base(assertions)
	_test_shanghai_deck_validates(assertions)
	_test_charm_move_contests_occupied_battlefield(assertions)


static func _test_charm_move_contests_occupied_battlefield(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {"calm": 2}}, "hand": ["charm"],
			 "battlefield-a": [{"id": "stalwart-poro", "owner": 0}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-b": [{"id": "chemtech-enforcer", "owner": 1}],
			 "deck_size": 5, "rune_deck_size": 12}
		]
	})
	# Move enemy unit onto the battlefield where P0 already has a unit → contested combat.
	h.cmd_with_choices(0, "play charm", ["chemtech-enforcer", "battlefield-a"])
	var bf = h.gs().board.battlefields[0]
	assertions.assert_true(
		not bf.units[0].is_empty() and not bf.units[1].is_empty(),
		"both sides have units after charm"
	)
	assertions.assert_true(
		bf.is_contested or not h.gs().board.staged_combats.is_empty() or h.gs().combat_bf_index >= 0,
		"charm move contests battlefield when both sides present"
	)


static func _test_zhonya_sacrifices_gear_on_lethal(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "zhonyas-hourglass"}, {"id": "chemtech-enforcer"}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var unit = h.find_unit("chemtech-enforcer")
	unit.add_damage(10)
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	assertions.assert_eq(unit.location, "base", "zhonya recalls lethal unit to base")
	assertions.assert_eq(unit.damage, 0, "zhonya heals recalled unit")
	assertions.assert_true(unit.is_exhausted, "zhonya exhausts recalled unit")
	assertions.assert_true(not unit in h.gs().players[0].trash, "zhonya prevents unit trash")
	var gear_in_trash := false
	for c in h.gs().players[0].trash:
		if c.definition.id == "zhonyas-hourglass":
			gear_in_trash = true
	assertions.assert_true(gear_in_trash, "zhonya gear is sacrificed to trash")
	unit.add_damage(10)
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	assertions.assert_true(unit in h.gs().players[0].trash, "second lethal death kills without gear")


static func _test_unyielding_prevents_spell_damage(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 4, "power": {"body": 2}}, "hand": ["unyielding-spirit", "hextech-ray"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play unyielding-spirit")
	assertions.assert_true(h.gs().prevent_spell_ability_damage, "unyielding sets prevention flag")
	h.cmd_with_choices(0, "play hextech-ray", ["chemtech-enforcer"])
	var unit = h.find_unit("chemtech-enforcer")
	assertions.assert_eq(unit.damage, 0, "unyielding blocks hextech-ray damage")
	unit.add_damage(1)
	assertions.assert_eq(unit.damage, 1, "direct add_damage still applies")


static func _test_defy_cost_filter(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 10, "power": {}}, "hand": ["find-your-center", "highlander"],
			 "base": [{"id": "chemtech-enforcer"}], "deck_size": 5, "rune_deck_size": 12},
			{"pool": {"energy": 4, "power": {"calm": 2}}, "hand": ["defy"], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller.submit_command(0, "play find-your-center")
	assertions.assert_true(not h.gs().chain.is_empty(), "find-your-center on chain")
	var item = h.gs().chain[h.gs().chain.size() - 1]
	assertions.assert_true(
		AbilityResolver._chain_item_matches_counter_limits(item, {"max_energy": 4, "max_power_total": 1}),
		"3-energy spell within defy limits"
	)
	h.controller.submit_command(1, "react defy")
	assertions.assert_true(not h.controller.last_command_error, "defy can react to find-your-center")
	h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 10, "power": {}}, "hand": ["highlander"],
			 "base": [{"id": "chemtech-enforcer"}], "deck_size": 5, "rune_deck_size": 12},
			{"pool": {"energy": 4, "power": {"calm": 2}}, "hand": ["defy"], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller.submit_command(0, "play highlander target chemtech-enforcer")
	item = h.gs().chain[h.gs().chain.size() - 1]
	# Force over-cost check via stricter params
	assertions.assert_true(
		not AbilityResolver._chain_item_matches_counter_limits(item, {"max_energy": 3, "max_power_total": 1}),
		"4-energy highlander exceeds max_energy 3"
	)
	# Also reject react when ability params would fail — simulate by checking helper only.


static func _test_find_your_center_cost_reduction(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"victory_score": 8,
		"players": [
			{"pool": {"energy": 1, "power": {}}, "hand": ["find-your-center"],
			 "deck_size": 5, "rune_deck_size": 4},
			{"score": 6, "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var card = h.gs().players[0].hand[0]
	var cost = CostCalculator.compute_play_cost(card, 0, h.gs())
	assertions.assert_eq(cost.get("energy", 99), 1, "find your center costs 1 when opponent within 3 of victory")
	h.cmd(0, "play find-your-center")
	assertions.assert_true(h.gs().players[0].hand.size() >= 1, "find your center draws 1")


static func _test_pit_rookie_buffs_other(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 4, "power": {}}, "hand": ["pit-rookie"],
			 "base": [{"id": "stalwart-poro"}, {"id": "clockwork-keeper"}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play pit-rookie", ["stalwart-poro"])
	var poro = h.find_unit("stalwart-poro")
	assertions.assert_true(poro != null and poro.buff_counters > 0, "pit rookie buffs chosen other unit")


static func _test_grove_hold_draw(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "BEGINNING", "state": "NEUTRAL_OPEN",
		"battlefields": ["grove-of-the-god-willow", "targons-peak"],
		"players": [
			{"deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().board.battlefields[0].controller_index = 0
	var hand_before = h.gs().players[0].hand.size()
	# Drive beginning hold via end turn into next beginning for P0
	h.gs().current_phase = TurnStateMachine.Phase.MAIN
	h.cmd(0, "end turn")
	h.cmd(1, "end turn")
	assertions.assert_true(
		h.gs().players[0].hand.size() > hand_before or h.gs().players[0].score >= 1,
		"grove hold scores and/or draws"
	)


static func _test_vilemaw_blocks_move_to_base(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["vilemaws-lair", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "stalwart-poro", "owner": 0, "exhausted": false}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller.submit_command(0, "move stalwart-poro to base")
	assertions.assert_true(h.controller.last_command_error, "vilemaw blocks move to base")
	assertions.assert_true(h.find_unit("stalwart-poro").is_at_battlefield(), "unit remains at vilemaw")


static func _test_shanghai_deck_validates(assertions) -> void:
	var data = DeckLoader.load_deck("res://Data/Decks/master-yi-shanghai-open.json")
	var errors = DeckLoader.validate(data)
	assertions.assert_true(errors.is_empty(), "shanghai master yi deck validates", str(errors))


static func _test_magma_wurm_aura(assertions) -> void:
	var h = _harness_with_play({"id": "chemtech-enforcer", "exhausted": true}, ["flame-chompers"], "magma-wurm", 20, [{"id": "fury-rune", "exhausted": false}])
	h.cmd(0, "play magma-wurm")
	var ally = h.find_unit("chemtech-enforcer")
	assertions.assert_true(ally != null and ally.is_exhausted, "magma wurm does not ready existing units")
	h.cmd(0, "play flame-chompers")
	var later = h.find_unit("flame-chompers")
	assertions.assert_true(later != null and not later.is_exhausted, "magma wurm makes later friendly units enter ready")


static func _test_meditation_exhaust_draws_two(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["meditation"],
			 "base": [{"id": "chemtech-enforcer", "exhausted": false}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play meditation", ["yes", "chemtech-enforcer"])
	var unit = h.find_unit("chemtech-enforcer")
	assertions.assert_true(unit != null and unit.is_exhausted, "meditation exhausts chosen friendly unit")
	assertions.assert_eq(h.gs().players[0].hand.size(), 2, "meditation draws 2 when custom cost is paid")


static func _test_ravenbloom_student_spell_trigger(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 1, "power": {"fury": 1}}, "hand": ["hextech-ray"],
			 "base": [{"id": "ravenbloom-student"}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play hextech-ray target chemtech-enforcer")
	assertions.assert_eq(h.find_unit("ravenbloom-student").get_current_might(), 3,
		"ravenbloom gets +1 when controller plays a spell")


static func _test_darius_second_card_trigger(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 7, "power": {}}, "hand": ["noxus-hopeful", "lecturing-yordle"],
			 "base": [{"id": "darius-trifarian", "exhausted": true}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play noxus-hopeful")
	var darius = h.find_unit("darius-trifarian")
	assertions.assert_true(darius.is_exhausted, "darius stays exhausted after first card")
	h.cmd(0, "play lecturing-yordle")
	assertions.assert_eq(darius.get_current_might(), 7, "darius gains +2 on second card")
	assertions.assert_true(not darius.is_exhausted, "darius readies on second card")


static func _test_kaisa_debuff_minimum(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["smoke-screen"], "deck_size": 5, "rune_deck_size": 12},
			{"base": [{"id": "watchful-sentry"}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play smoke-screen target watchful-sentry")
	assertions.assert_eq(h.find_unit("watchful-sentry").get_current_might(), 1,
		"smoke screen cannot reduce below 1 Might")


static func _test_falling_star_can_repeat_target(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {"fury": 2}}, "hand": ["falling-star"], "deck_size": 5, "rune_deck_size": 12},
			{"base": [{"id": "magma-wurm"}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play falling-star target magma-wurm", ["magma-wurm"])
	assertions.assert_eq(h.find_unit("magma-wurm").damage, 6, "falling star can choose same unit twice")
	assertions.assert_eq(h.gs().players[0].rune_pool.power.get("fury", 0), 0,
		"falling star spends 2 fury power")


static func _test_falling_star_requires_fury_power(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["falling-star"], "deck_size": 5, "rune_deck_size": 12},
			{"base": [{"id": "magma-wurm"}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var card = h.gs().players[0].hand[0]
	var cost = CostCalculator.compute_play_cost(card, 0, h.gs())
	assertions.assert_eq(cost.get("energy", -1), 2, "falling star energy cost is 2")
	assertions.assert_eq(cost.get("power", []).size(), 1, "falling star has one power requirement")
	assertions.assert_eq(str(cost["power"][0].get("domain", "")), "fury", "falling star power is fury")
	assertions.assert_eq(int(cost["power"][0].get("amount", 0)), 2, "falling star costs 2 fury power")
	h.cmd(0, "play falling-star target magma-wurm")
	assertions.assert_eq(h.gs().players[0].hand.size(), 1, "falling star stays in hand without power")
	assertions.assert_eq(h.find_unit("magma-wurm").damage, 0, "falling star does not resolve unpaid")


static func _test_noxus_hopeful_legion_cost(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 7, "power": {}}, "hand": ["noxus-hopeful", "lecturing-yordle"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var hopeful = h.gs().players[0].hand[0]
	var base_cost = CostCalculator.compute_play_cost(hopeful, 0, h.gs())
	assertions.assert_eq(base_cost.get("energy", -1), 4, "noxus hopeful base energy is 4")

	# First play establishes Legion for the next card.
	h.cmd(0, "play lecturing-yordle")
	hopeful = null
	for c in h.gs().players[0].hand:
		if c.definition.id == "noxus-hopeful":
			hopeful = c
			break
	assertions.assert_true(hopeful != null, "noxus hopeful still in hand")
	var legion_cost = CostCalculator.compute_play_cost(hopeful, 0, h.gs())
	assertions.assert_eq(legion_cost.get("energy", -1), 2,
		"noxus hopeful costs 2 energy with Legion (not double-reduced to 0)")
	h.cmd(0, "play noxus-hopeful")
	assertions.assert_eq(h.gs().players[0].rune_pool.energy, 2,
		"playing noxus hopeful with Legion spends 2 energy")
	assertions.assert_true(h.find_unit("noxus-hopeful") != null, "noxus hopeful enters play")


static func _test_sprite_mother_token_here_temporary(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{"pool": {"energy": 4, "power": {}}, "hand": ["sprite-mother"], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play sprite-mother to battlefield-a")
	var token = h.find_unit("sprite-3m")
	assertions.assert_true(token != null and token.is_at_battlefield(), "sprite token is played at battlefield")
	assertions.assert_true(not token.is_exhausted, "sprite token enters ready")
	assertions.assert_true(token.has_keyword("temporary"), "sprite token has Temporary")
	h.controller._kill_temporary_permanents(0)
	assertions.assert_true(token in h.gs().players[0].trash, "temporary sprite dies at beginning phase")


static func _test_dr_mundo_trash_might_and_recycle(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"legend": "kaisa-daughter-of-the-void",
			 "base": [{"id": "dr-mundo-expert"}], "trash": ["hextech-ray", "cleave", "stupefy"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	assertions.assert_eq(h.find_unit("dr-mundo-expert").get_current_might(), 9,
		"dr mundo gains Might for cards in trash")
	var deck_before = h.gs().players[0].deck.size()
	h.controller.trigger_dispatcher.emit("beginning_phase_start", {
		"player_index": 0, "controller": h.controller
	}, h.gs(), h.controller)
	assertions.assert_eq(h.gs().players[0].trash.size(), 0, "dr mundo recycles three from trash")
	assertions.assert_eq(h.gs().players[0].deck.size(), deck_before + 3, "dr mundo puts recycled cards into deck")


static func _test_retreat_returns_and_channels(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 1, "power": {}}, "hand": ["retreat"],
			 "base": [{"id": "chemtech-enforcer"}], "deck_size": 5, "rune_deck_size": 2},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play retreat target chemtech-enforcer")
	assertions.assert_true(h.gs().players[0].get_hand_instance("chemtech-enforcer") != null,
		"retreat returns friendly unit to hand")
	assertions.assert_eq(h.gs().players[0].channeled_runes.size(), 1, "retreat channels one rune")
	assertions.assert_true(h.gs().players[0].channeled_runes[0].is_exhausted, "retreat rune enters exhausted")


static func _test_meditation_decline_draws_one(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["meditation"],
			 "base": [{"id": "chemtech-enforcer", "exhausted": false}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play meditation", ["no"])
	var unit = h.find_unit("chemtech-enforcer")
	assertions.assert_true(unit != null and not unit.is_exhausted, "meditation decline does not exhaust unit")
	assertions.assert_eq(h.gs().players[0].hand.size(), 1, "meditation draws 1 when custom cost is declined")


static func _test_meditation_no_ready_friendly_draws_one(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["meditation"],
			 "base": [{"id": "chemtech-enforcer", "exhausted": true}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play meditation")
	assertions.assert_eq(h.gs().players[0].hand.size(), 1, "meditation draws 1 with no ready friendly unit")


static func _test_highlander_replaces_next_death(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 4, "power": {}}, "hand": ["highlander"],
			 "battlefield-a": [{"id": "chemtech-enforcer", "owner": 0}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play highlander", ["chemtech-enforcer"])
	var unit = h.find_unit("chemtech-enforcer")
	unit.add_damage(10)
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	assertions.assert_eq(unit.location, "base", "highlander recalls lethal unit to base")
	assertions.assert_eq(unit.damage, 0, "highlander heals recalled unit")
	assertions.assert_true(unit.is_exhausted, "highlander exhausts recalled unit")
	assertions.assert_true(not unit in h.gs().players[0].trash, "highlander replacement prevents death")


static func _test_highlander_expires_end_of_turn(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 4, "power": {}}, "hand": ["highlander"],
			 "base": [{"id": "chemtech-enforcer"}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play highlander", ["chemtech-enforcer"])
	var unit = h.find_unit("chemtech-enforcer")
	h.cmd(0, "end turn")
	unit.add_damage(10)
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	assertions.assert_true(unit in h.gs().players[0].trash, "highlander replacement expires at end of turn")


static func _test_reavers_row_choose_defender(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["reavers-row", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "magma-wurm", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}, {"id": "flame-chompers", "owner": 1}],
			 "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.set_choices(["yes", "flame-chompers"])
	for line in CombatProcessor.begin_combat(0, 0, h.gs(), h.controller):
		h.controller.log_lines.append(line)
	h._drain_prompts(1)
	assertions.assert_eq(h.find_unit("flame-chompers").location, "base", "reavers row recalls chosen defender")
	assertions.assert_true(h.find_unit("chemtech-enforcer").is_at_battlefield(), "reavers row leaves unchosen defender")


static func _test_fortified_position_choose_defender(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["fortified-position", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "magma-wurm", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}, {"id": "flame-chompers", "owner": 1}],
			 "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.set_choices(["yes", "flame-chompers"])
	for line in CombatProcessor.begin_combat(0, 0, h.gs(), h.controller):
		h.controller.log_lines.append(line)
	h._drain_prompts(1)
	assertions.assert_eq(h.find_unit("flame-chompers").get_keyword_value("shield"), 2,
		"fortified position shields chosen defender")
	assertions.assert_eq(h.find_unit("chemtech-enforcer").get_keyword_value("shield"), 0,
		"fortified position leaves unchosen defender")


static func _test_traveling_merchant_on_move(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "traveling-merchant", "exhausted": false}], "hand": ["fury-rune"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "move traveling-merchant to battlefield-a", ["fury-rune"])
	assertions.assert_log_contains(h.controller, "discarded", "traveling merchant discards on move")


# BUG-012: on_move must fire when returning to base, not only when moving to a battlefield.
static func _test_traveling_merchant_on_move_to_base(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"battlefield-a": [{"id": "traveling-merchant", "exhausted": false}],
				"hand": ["fury-rune"],
				"deck_size": 5, "rune_deck_size": 12,
			},
			{"deck_size": 5, "rune_deck_size": 12},
		],
	})
	h.cmd_with_choices(0, "move traveling-merchant to base", ["fury-rune"])
	assertions.assert_log_contains(
		h.controller, "discarded", "traveling merchant discards on move to base"
	)


# BUG-008: on_move triggers must fire only for the unit that moved.
static func _test_traveling_merchant_not_on_other_move(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 1, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, 1],
		"players": [
			{
				"battlefield-a": [{"id": "traveling-merchant", "exhausted": true}],
				"hand": ["fury-rune"],
				"deck_size": 5, "rune_deck_size": 12,
			},
			{
				"base": [{"id": "flame-chompers", "exhausted": false}],
				"hand": ["void-seeker"],
				"deck_size": 5, "rune_deck_size": 12,
			},
		],
	})
	var merchant_owner_hand := h.gs().players[0].hand.size()
	h.cmd(1, "move flame-chompers to battlefield-b")
	assertions.assert_no_error(h.controller, "opponent move succeeds")
	assertions.assert_eq(
		h.gs().players[0].hand.size(),
		merchant_owner_hand,
		"traveling merchant owner hand unchanged when another unit moves"
	)
	var merchant_discarded := false
	for line in h.controller.log_lines:
		if "P1 discarded" in line:
			merchant_discarded = true
			break
	assertions.assert_true(
		not merchant_discarded,
		"traveling merchant does not discard on other unit move"
	)


static func _test_scrapheap_on_play(assertions) -> void:
	var h = _harness_with_play({}, [], "scrapheap")
	h.cmd(0, "play scrapheap")
	assertions.assert_log_contains(h.controller, "drew", "scrapheap draws on play")


static func _test_rhasa_cost_reduction(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 15, "power": {}}, "hand": ["rhasa-the-sunderer"],
			 "trash": [{"id": "fury-rune"}, {"id": "fury-rune"}, {"id": "fury-rune"}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var cost = CostCalculator.compute_play_cost(h.find_unit("rhasa-the-sunderer") if false else h.gs().players[0].hand[0], 0, h.gs())
	assertions.assert_true(cost.get("energy", 99) < 10, "rhasa cost reduced by trash count")


static func _test_gust_might_filter(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_CLOSED",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["gust"], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "magma-wurm", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var targets = TargetResolver.filter_with_params("unit_at_battlefield", {"condition": {"type": "might_lte", "value": 3}}, null, h.gs(), {"player_index": 0})
	assertions.assert_true(targets.is_empty(), "gust cannot target might > 3")

	var h2 = TcgTestHarness.new()
	h2.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_CLOSED",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["gust"], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "flame-chompers", "owner": 1,
				"keywords": [{"id": "shield", "value": 1}]}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var chompers = h2.find_unit("flame-chompers")
	chompers.is_defender = true
	var boosted_targets = TargetResolver.filter_with_params("unit_at_battlefield", {"condition": {"type": "might_lte", "value": 3}}, null, h2.gs(), {"player_index": 0})
	assertions.assert_true(boosted_targets.is_empty(), "gust cannot target current might > 3")

	var h3 = TcgTestHarness.new()
	h3.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_CLOSED",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 2, "power": {}}, "hand": ["gust"], "deck_size": 5, "rune_deck_size": 12},
			{"legend": "master-yi-wuju-bladesman",
			 "battlefield-a": [{"id": "stalwart-poro", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var poro = h3.find_unit("stalwart-poro")
	poro.is_defender = true
	h3.gs().combat_bf_index = 0
	h3.controller.trigger_dispatcher.emit_passive_auras(h3.gs())
	h3.controller.submit_command(0, "play gust target stalwart-poro")
	assertions.assert_true(h3.controller.last_command_error, "gust rejects explicit invalid target")
	assertions.assert_log_contains(h3.controller, "Invalid target 'stalwart-poro'", "gust direct target is filter checked")


static func _test_gust_rechecks_might_on_resolution(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "SHOWDOWN_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"hand": ["gust"], "pool": {"energy": 1}, "deck_size": 5, "rune_deck_size": 12},
			{"hand": ["en-garde"], "pool": {"energy": 1},
			 "battlefield-a": [{"id": "flame-chompers", "owner": 1}],
			 "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().focus_player_index = 0
	h.gs().board.active_showdown_bf = 0

	h.controller.submit_command(0, "react gust target flame-chompers")
	h.controller.submit_command(1, "react en-garde target flame-chompers")
	h.controller.submit_command(0, "pass")
	h.controller.submit_command(1, "pass")
	assertions.assert_eq(h.find_unit("flame-chompers").get_current_might(), 5,
		"reaction raises Gust target above 3 Might")

	h.controller.submit_command(0, "pass")
	h.controller.submit_command(1, "pass")
	var chompers = h.find_unit("flame-chompers")
	assertions.assert_true(chompers != null and chompers.is_at_battlefield(),
		"gust does not return a target that became invalid before resolution")
	assertions.assert_true(h.gs().players[1].get_hand_instance("flame-chompers") == null,
		"invalid Gust target remains at the battlefield")
	assertions.assert_log_contains(h.controller, "target is no longer valid",
		"gust logs that its target failed resolution-time validation")


static func _test_fight_or_flight_move_base(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["fight-or-flight"],
			 "battlefield-a": [{"id": "vi-destructive", "owner": 1}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play fight-or-flight", ["vi-destructive"])
	assertions.assert_log_contains(h.controller, "moved to base", "fight or flight returns unit to base")


static func _test_gentlemens_duel_applies_buffed_fight_damage(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "SHOWDOWN_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 6, "power": {"body": 1}}, "hand": ["gentlemens-duel"],
			 "battlefield-a": [{"id": "zephyr-sage", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().focus_player_index = 0
	h.cmd_with_choices(0, "play gentlemens-duel", ["zephyr-sage", "chemtech-enforcer"])
	var friendly = h.find_unit("zephyr-sage")
	assertions.assert_true(friendly != null and friendly.damage == 2,
		"gentlemens duel friendly takes enemy might as reciprocal damage")
	assertions.assert_true(h.gs().board.find_unit_on_board("chemtech-enforcer") == null and
			h.gs().players[1].find_instance("chemtech-enforcer") != null,
		"gentlemens duel uses buffed might to kill chosen enemy")


static func _test_brazen_buccaneer_discount(assertions) -> void:
	var h = _harness_with_play({"id": "brazen-buccaneer"}, [], "brazen-buccaneer", 6)
	var cost = CostCalculator.compute_play_cost(h.gs().players[0].hand[0], 0, h.gs(), false, true)
	assertions.assert_true(cost.get("energy", 6) <= 4, "brazen buccaneer optional discard reduces cost")


static func _test_cemetery_attendant(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["cemetery-attendant"],
			 "runes": [{"id": "chaos-rune", "exhausted": false}],
			 "trash": [{"id": "chemtech-enforcer"}, {"id": "flame-chompers"}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play cemetery-attendant", ["flame-chompers"])
	assertions.assert_true(h.gs().players[0].get_hand_instance("flame-chompers") != null,
		"cemetery attendant returns chosen unit from trash")
	assertions.assert_true(h.gs().players[0].find_instance("chemtech-enforcer") in h.gs().players[0].trash,
		"cemetery attendant leaves unchosen trash unit")


static func _test_get_excited(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["get-excited", "void-seeker"],
			 "runes": [{"id": "fury-rune", "exhausted": false}],
			 "battlefield-a": [{"id": "blazing-scorcher", "owner": 1}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play get-excited", ["blazing-scorcher", "void-seeker"])
	assertions.assert_log_contains(h.controller, "damage", "get excited deals damage")


# BUG-010 / GitHub #47: Reaction spells add extra timing windows but remain
# playable during the turn player's normal open main-phase window.
static func _test_reaction_spell_playable_in_neutral_open(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 1, "power": {}}, "hand": ["gust"],
			 "battlefield-a": [{"id": "flame-chompers", "owner": 1}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play gust", ["flame-chompers"])
	assertions.assert_no_error(h.controller, "reaction spell plays during neutral open")
	assertions.assert_eq(h.gs().board.find_unit_on_board("flame-chompers"), null,
		"gust resolves after being played in neutral open")


static func _test_jinx_demolitionist_discard(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 10, "power": {"fury": 1}},
				"hand": ["jinx-demolitionist", "fury-rune", "fury-rune", "void-seeker"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12},
		],
	})
	h.cmd_with_choices(0, "play jinx-demolitionist", ["fury-rune", "void-seeker"])
	assertions.assert_log_contains(h.controller, "discarded", "jinx demolitionist discards on play")


static func _test_vi_recycle_cost(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 0, "power": {}}, "battlefield-a": [{"id": "vi-destructive", "owner": 0}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var deck_before = h.gs().players[0].deck.duplicate()
	h.cmd(0, "use vi-destructive")
	assertions.assert_log_contains(h.controller, "Might", "vi recycle cost consumes deck card")


static func _test_raging_soul_keywords(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "raging-soul"}], "deck_size": 5, "rune_deck_size": 12,
			 "cards_discarded_count": 1},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().players[0].cards_discarded_count = 1
	h.controller.trigger_dispatcher.emit_passive_auras(h.gs())
	var unit = h.find_unit("raging-soul")
	assertions.assert_true(unit.has_keyword("ganking"), "raging soul gains ganking after discard")


static func _test_zaun_warrens_conquer(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"hand": ["fury-rune", "fury-rune"], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.set_choices(["fury-rune"])
	ShowdownProcessor.establish_control(h.gs(), 0, 0, true, h.controller)
	h._drain_prompts(0)
	assertions.assert_log_contains(h.controller, "discarded", "zaun warrens discard_then_draw on conquer")


static func _test_targons_peak_ready_runes(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["targons-peak", "zaun-warrens"],
		"players": [
			{"runes": [{"id": "fury-rune", "exhausted": true}, {"id": "fury-rune", "exhausted": true}],
			 "deck_size": 5, "rune_deck_size": 10},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	ShowdownProcessor.establish_control(h.gs(), 0, 0, true, h.controller)
	h.controller.trigger_dispatcher.process_end_of_turn(h.gs(), h.controller)
	assertions.assert_true(not h.gs().players[0].channeled_runes[0].is_exhausted, "targons peak readies runes")


static func _test_fading_memories_temporary(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["fading-memories"],
			 "runes": [{"id": "chaos-rune", "exhausted": false}],
			 "battlefield-a": [{"id": "chemtech-enforcer", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play fading-memories", ["chemtech-enforcer"])
	var target = h.find_unit("chemtech-enforcer")
	assertions.assert_true(target.has_keyword("temporary"), "fading memories grants temporary")
	h.cmd(0, "end turn")
	assertions.assert_true(target.has_keyword("temporary"), "temporary survives until controller's beginning phase")
	h.cmd(1, "end turn")
	assertions.assert_eq(target.location, "trash", "temporary kills at controller's beginning phase")
	assertions.assert_eq(h.gs().players[0].score, 0, "temporary dies before hold scoring")


static func _test_undercover_agent_deathknell(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"base": [{"id": "undercover-agent", "damage": 6}], "hand": ["fury-rune", "fury-rune"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.set_choices(["fury-rune", "fury-rune"])
	CleanupProcessor.run(h.gs(), h.controller.ability_resolver, h.controller)
	h._drain_prompts(0)
	assertions.assert_log_contains(h.controller, "discarded", "undercover agent deathknell discard_then_draw")


static func _test_chemtech_discards_once(assertions) -> void:
	var h = _harness_with_play({}, ["fight-or-flight", "blazing-scorcher"], "chemtech-enforcer", 5)
	var hand_before = h.gs().players[0].hand.size()
	h.cmd_with_choices(0, "play chemtech-enforcer", ["fight-or-flight"])
	assertions.assert_eq(h.gs().players[0].trash.size(), 1, "chemtech discards exactly one card")
	assertions.assert_eq(h.gs().players[0].hand.size(), hand_before - 2, "one card played, one discarded")


static func _test_blazing_scorcher_discard_no_prompt(assertions) -> void:
	var h = _harness_with_play({}, ["blazing-scorcher", "void-seeker"], "chemtech-enforcer", 5)
	h.cmd_with_choices(0, "play chemtech-enforcer", ["blazing-scorcher"])
	var has_accel_prompt = false
	for line in h.controller.log_lines:
		if "Optional ability (Blazing Scorcher)" in line:
			has_accel_prompt = true
			break
	assertions.assert_true(not has_accel_prompt, "blazing scorcher discard does not prompt accelerate")
	assertions.assert_true(h.gs().players[0].trash.size() >= 1, "blazing scorcher discarded")


static func _test_flame_chompers_discard_prompts(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {"fury": 1}}, "hand": ["chemtech-enforcer", "flame-chompers", "void-seeker"],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play chemtech-enforcer", ["flame-chompers", "yes"])
	assertions.assert_log_contains(h.controller, "Flame Chompers", "flame chompers named in optional prompt")
	assertions.assert_log_contains(h.controller, "played itself", "flame chompers play_self on discard")
	assertions.assert_eq(h.gs().players[0].cards_played_this_turn, 2,
		"flame chompers play_self counts as a played card")


static func _test_flame_chompers_not_on_other_discard(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 10, "power": {"fury": 2}},
			 "hand": ["jinx-demolitionist", "brazen-buccaneer", "fury-rune", "void-seeker"],
			 "base": [{"id": "flame-chompers"}], "deck_size": 5, "rune_deck_size": 12},
			{"base": [{"id": "flame-chompers"}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play jinx-demolitionist", ["brazen-buccaneer", "void-seeker"])
	var has_chompers_prompt = false
	for line in h.controller.log_lines:
		if "Optional ability (Flame Chompers)" in line:
			has_chompers_prompt = true
			break
	assertions.assert_true(not has_chompers_prompt, "flame chompers on board does not trigger when another card is discarded")


static func _test_scrapheap_on_discard_effect(assertions) -> void:
	var h = _harness_with_play({}, ["scrapheap", "void-seeker"], "chemtech-enforcer", 5)
	h.cmd_with_choices(0, "play chemtech-enforcer", ["scrapheap"])
	assertions.assert_log_contains(h.controller, "drew", "scrapheap draws on discard")
	assertions.assert_true(h.gs().pending_prompt.is_empty(), "scrapheap on_discard draw clears discard prompt")


static func _test_p2_can_act_after_chemtech_scrapheap_turn(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN", "turn_number": 1,
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["chemtech-enforcer", "scrapheap", "void-seeker"],
			 "runes": [{"id": "fury-rune"}, {"id": "chaos-rune"}],
			 "deck_size": 10, "rune_deck_size": 12},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play chemtech-enforcer", ["scrapheap"])
	h.cmd(0, "end turn")
	assertions.assert_true(h.gs().pending_prompt.is_empty(), "no stale prompt after p1 end turn")
	assertions.assert_eq(h.gs().turn_player_index, 1, "turn passes to p2")
	assertions.assert_true(h.gs().can_player_act(1), "p2 can act at turn 2 start for ai trigger")


# BUG-008: an inline target above the spell's Might threshold must be rejected
# at play time, before the spell is paid for or placed on the Chain.
static func _test_gust_rejects_target_above_might(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "SHOWDOWN_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"hand": ["gust"], "pool": {"energy": 1}, "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "magma-wurm", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().focus_player_index = 0
	h.gs().board.active_showdown_bf = 0
	h.controller.submit_command(0, "react gust target magma-wurm")
	assertions.assert_true(h.controller.last_command_error,
		"gust cannot target a unit with Might above 3")
	assertions.assert_eq(h.gs().players[0].hand.size(), 1,
		"gust stays in hand after rejected target")


# Targeted spells expose one explicit target per legal target (locked at play
# time) and no bare untargeted play.
static func _test_play_targeted_spell_enumerates_targets(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {"fury": 1}}, "hand": ["void-seeker"],
			 "runes": [{"id": "fury-rune", "exhausted": false}],
			 "battlefield-a": [{"id": "blazing-scorcher", "owner": 1}],
			 "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true("play void-seeker target blazing-scorcher" in moves,
		"targeted spell enumerates an explicit target option")
	assertions.assert_true(not ("play void-seeker" in moves),
		"targeted spell does not offer an untargeted play")


static func _harness_with_play(base_ally: Dictionary, extra_hand: Array, play_id: String = "", energy: int = 10, runes: Array = []) -> TcgTestHarness:
	var h = TcgTestHarness.new()
	var base: Array = []
	if not base_ally.is_empty():
		base.append(base_ally)
	var hand: Array = []
	if not play_id.is_empty():
		hand.append(play_id)
	hand.append_array(extra_hand)
	var p0: Dictionary = {
		"pool": {"energy": energy, "power": {}},
		"hand": hand,
		"base": base,
		"deck_size": 10,
		"rune_deck_size": 12,
	}
	if not runes.is_empty():
		p0["runes"] = runes
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			p0,
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	return h
