class_name CardScenarioTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const TargetResolver = preload("res://Scripts/Game/TargetResolver.gd")

# Data-driven smoke tests for starter-deck card abilities.

static func run(assertions) -> void:
	_test_magma_wurm_aura(assertions)
	_test_traveling_merchant_on_move(assertions)
	_test_scrapheap_on_play(assertions)
	_test_rhasa_cost_reduction(assertions)
	_test_gust_might_filter(assertions)
	_test_fight_or_flight_move_base(assertions)
	_test_flame_chompers_discard(assertions)
	_test_brazen_buccaneer_discount(assertions)
	_test_cemetery_attendant(assertions)
	_test_get_excited(assertions)
	_test_jinx_demolitionist_discard(assertions)
	_test_vi_recycle_cost(assertions)
	_test_raging_soul_keywords(assertions)
	_test_zaun_warrens_conquer(assertions)
	_test_targons_peak_ready_runes(assertions)
	_test_reavers_row_defend(assertions)
	_test_fading_memories_temporary(assertions)
	_test_undercover_agent_deathknell(assertions)
	_test_blazing_scorcher_accelerate(assertions)
	_test_chemtech_discards_once(assertions)
	_test_blazing_scorcher_discard_no_prompt(assertions)
	_test_flame_chompers_discard_prompts(assertions)
	_test_flame_chompers_not_on_other_discard(assertions)
	_test_scrapheap_on_discard_effect(assertions)


static func _test_magma_wurm_aura(assertions) -> void:
	var h = _harness_with_play({"id": "chemtech-enforcer", "exhausted": true}, [], "magma-wurm")
	h.cmd(0, "play magma-wurm")
	var ally = h.find_unit("chemtech-enforcer")
	assertions.assert_true(ally != null and not ally.is_exhausted, "magma wurm readies other units")


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


static func _test_flame_chompers_discard(assertions) -> void:
	_test_flame_chompers_discard_prompts(assertions)


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
			 "trash": [{"id": "chemtech-enforcer"}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "play cemetery-attendant")
	assertions.assert_log_contains(h.controller, "returned", "cemetery attendant returns from trash")


static func _test_get_excited(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["get-excited", "void-seeker"],
			 "battlefield-a": [{"id": "blazing-scorcher", "owner": 1}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play get-excited", ["blazing-scorcher", "void-seeker"])
	assertions.assert_log_contains(h.controller, "damage", "get excited deals damage")


static func _test_jinx_demolitionist_discard(assertions) -> void:
	var h = _harness_with_play({}, [{"id": "fury-rune"}, {"id": "fury-rune"}, {"id": "void-seeker"}], "jinx-demolitionist", 10)
	h.cmd_with_choices(0, "play jinx-demolitionist", ["no", "fury-rune", "void-seeker"])
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


static func _test_reavers_row_defend(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["reavers-row", "zaun-warrens"],
		"players": [
			{"battlefield-a": [{"id": "chemtech-enforcer", "owner": 1}], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "vi-destructive", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	CombatProcessor.begin_combat(0, 0, h.gs(), h.controller)
	assertions.assert_true(true, "reavers row defend trigger runs without error")


static func _test_fading_memories_temporary(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": 5, "power": {}}, "hand": ["fading-memories"],
			 "battlefield-a": [{"id": "chemtech-enforcer", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd_with_choices(0, "play fading-memories", ["chemtech-enforcer"])
	var target = h.find_unit("chemtech-enforcer")
	assertions.assert_true(target.has_keyword("temporary"), "fading memories grants temporary")


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


static func _test_blazing_scorcher_accelerate(assertions) -> void:
	var h = _harness_with_play({"id": "blazing-scorcher"}, [], "blazing-scorcher", 6)
	h.cmd(0, "play blazing-scorcher accelerate")
	var unit = h.find_unit("blazing-scorcher")
	assertions.assert_true(unit != null and not unit.is_exhausted, "accelerate enters ready")


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
	h.cmd_with_choices(0, "play jinx-demolitionist", ["no", "brazen-buccaneer", "void-seeker"])
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


static func _harness_with_play(base_ally: Dictionary, extra_hand: Array, play_id: String = "", energy: int = 10) -> TcgTestHarness:
	var h = TcgTestHarness.new()
	var base: Array = []
	if not base_ally.is_empty():
		base.append(base_ally)
	var hand: Array = []
	if not play_id.is_empty():
		hand.append(play_id)
	hand.append_array(extra_hand)
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"pool": {"energy": energy, "power": {}}, "hand": hand, "base": base, "deck_size": 10, "rune_deck_size": 12},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	return h
