class_name RuleResourcesTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const BriefStateSerializerScript = preload("res://Scripts/AI/BriefStateSerializer.gd")

static func run(assertions) -> void:
	_test_tap_adds_energy(assertions)
	_test_accelerate_auto_recycles_rune(assertions)
	_test_on_discard_power_auto_recycles_rune(assertions)
	_test_accelerate_taps_before_recycle_for_energy(assertions)
	_test_jinx_base_cost_recycles_for_power(assertions)
	_test_jinx_legal_moves_accelerate_requires_four_runes(assertions)
	_test_play_without_accelerate_skips_prompt(assertions)
	_test_accelerate_requires_energy_when_pool_has_power(assertions)
	_test_hidden_unaffordable_play_not_legal(assertions)
	_test_hidden_hide_requires_any_power(assertions)
	_test_hidden_hide_auto_recycles_rune(assertions)
	_test_hidden_hide_only_at_controlled_empty_facedown(assertions)
	_test_hidden_hide_from_champion_zone(assertions)
	_test_hidden_lost_control_trashes_facedown(assertions)
	_test_play_from_hidden_facedown_card(assertions)
	_test_play_from_hidden_target_restricted_to_hidden_battlefield(assertions)
	_test_kaisa_spell_rainbow_pays_spell_only(assertions)
	_test_kaisa_spell_rainbow_legal_moves(assertions)
	_test_kaisa_legend_in_brief_state(assertions)


static func _test_tap_adds_energy(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture("res://Scripts/Tests/Tcg/fixtures/resources_tap_rune.json")
	h.cmd(0, "tap rune-0")
	assertions.assert_eq(h.gs().players[0].rune_pool.energy, 1, "tap adds 1 energy")
	assertions.assert_no_error(h.controller, "tap rune succeeds")


static func _test_kaisa_spell_rainbow_pays_spell_only(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"legend": "kaisa-daughter-of-the-void", "pool": {"energy": 3, "power": {}},
			 "hand": ["void-seeker"], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "magma-wurm", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "use legend-p0")
	assertions.assert_eq(h.gs().players[0].rune_pool.power.get(RunePool.SPELL_RAINBOW_POWER, 0), 1,
		"kaisa legend adds spell-only rainbow power")
	h.cmd(0, "play void-seeker target magma-wurm")
	assertions.assert_no_error(h.controller, "spell-only rainbow pays for spell power")
	assertions.assert_eq(h.gs().players[0].rune_pool.power.get(RunePool.SPELL_RAINBOW_POWER, 0), 0,
		"spell-only rainbow is spent by spell")


static func _test_kaisa_spell_rainbow_legal_moves(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"legend": "kaisa-daughter-of-the-void", "pool": {"energy": 3, "power": {"spell_rainbow": 1}},
			 "hand": ["void-seeker", "jinx-demolitionist"], "deck_size": 5, "rune_deck_size": 12},
			{"battlefield-a": [{"id": "magma-wurm", "owner": 1}], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true("play void-seeker target magma-wurm" in moves,
		"spell-only rainbow makes matching spell legal")
	assertions.assert_true(not ("play jinx-demolitionist" in moves),
		"spell-only rainbow does not make unit power costs legal")


static func _test_kaisa_legend_in_brief_state(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"legend": "kaisa-daughter-of-the-void", "pool": {"energy": 3, "power": {}},
			 "hand": ["void-seeker"], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	var brief: Dictionary = BriefStateSerializerScript.serialize(h.gs(), 0, false)
	var legend = brief.get("my_legend", null)
	assertions.assert_true(legend is Dictionary, "brief state includes my_legend")
	assertions.assert_eq(str(legend.get("instance_id", "")), "legend-p0", "legend instance id")
	assertions.assert_true(str(legend.get("name", "")).find("Kai") >= 0, "legend name is present")
	assertions.assert_eq(bool(legend.get("is_exhausted", true)), false, "legend starts ready")
	assertions.assert_true(str(legend.get("effect_text", "")).find("rainbow") >= 0,
		"legend effect text describes the rainbow rune")
	var abilities: Array = legend.get("abilities", [])
	assertions.assert_true(not abilities.is_empty(), "legend abilities are listed")
	assertions.assert_eq(str(abilities[0].get("ability_type", "")), "activated",
		"Kai'Sa legend ability is activated")
	assertions.assert_eq(bool(abilities[0].get("is_reaction", false)), true,
		"Kai'Sa legend ability is a Reaction")
	var cats: Array = brief.get("legal_action_categories", [])
	assertions.assert_true("use_ability" in cats, "legal categories include use_ability")
	assertions.assert_true("use legend-p0" in brief.get("legal_moves", []),
		"legal moves include use legend-p0")


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


# BUG-004: auto-recycle must tap an untapped rune for energy before recycling it for power.
static func _test_accelerate_taps_before_recycle_for_energy(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["jinx-demolitionist", "void-seeker", "fury-rune"],
				"runes": [
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
					{"id": "chaos-rune", "exhausted": false},
					{"id": "chaos-rune", "exhausted": false},
				],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	h.set_choices(["void-seeker", "fury-rune"])
	h.cmd(0, "play jinx-demolitionist accelerate")
	assertions.assert_no_error(h.controller, "jinx demolitionist accelerate succeeds with four runes")
	assertions.assert_true(h.find_unit("jinx-demolitionist") != null, "jinx demolitionist enters play")


# BUG-009: base domain power must auto-recycle; do not spend all runes on energy only.
static func _test_jinx_base_cost_recycles_for_power(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["jinx-demolitionist", "void-seeker", "fury-rune"],
				"runes": [
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
				],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var rune_deck_before = h.gs().players[0].rune_deck.size()
	h.set_choices(["void-seeker", "fury-rune"])
	h.cmd(0, "play jinx-demolitionist")
	assertions.assert_no_error(h.controller, "jinx base cost succeeds with three runes")
	assertions.assert_log_contains(h.controller, "[Auto] Rune recycled", "base fury power auto-recycles a rune")
	assertions.assert_eq(h.gs().players[0].rune_deck.size(), rune_deck_before + 1, "one rune returned to rune deck")
	assertions.assert_eq(h.gs().players[0].channeled_runes.size(), 2, "two runes remain channeled after recycle")
	var unit = h.find_unit("jinx-demolitionist")
	assertions.assert_true(unit != null and unit.is_exhausted, "jinx enters exhausted without accelerate")


static func _test_jinx_legal_moves_accelerate_requires_four_runes(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["jinx-demolitionist", "void-seeker", "fury-rune"],
				"runes": [
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
				],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true(
		"play jinx-demolitionist" in moves,
		"three runes: base jinx play is legal",
	)
	assertions.assert_true(
		not ("play jinx-demolitionist accelerate" in moves),
		"three runes: jinx accelerate is not legal",
	)


static func _test_accelerate_requires_energy_when_pool_has_power(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 4, "power": {"fury": 1}},
				"hand": ["jinx-demolitionist", "void-seeker", "fury-rune"],
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	h.set_choices(["void-seeker", "fury-rune"])
	h.cmd(0, "play jinx-demolitionist accelerate")
	assertions.assert_no_error(h.controller, "accelerate succeeds when pool covers energy and rune covers extra power")
	assertions.assert_log_contains(h.controller, "[Auto] Rune recycled", "accelerate recycles for second fury power")
	var unit = h.find_unit("jinx-demolitionist")
	assertions.assert_true(unit != null and not unit.is_exhausted, "accelerate enters ready")


static func _test_play_without_accelerate_skips_prompt(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["jinx-demolitionist", "void-seeker", "fury-rune"],
				"runes": [
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
					{"id": "fury-rune", "exhausted": false},
				],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	h.set_choices(["void-seeker", "fury-rune"])
	h.cmd(0, "play jinx-demolitionist")
	var has_accel_prompt := false
	for line in h.controller.log_lines:
		if "Pay Accelerate on" in line:
			has_accel_prompt = true
	assertions.assert_true(
		not has_accel_prompt,
		"play without accelerate keyword does not prompt for accelerate",
	)
	assertions.assert_no_error(h.controller, "jinx plays without accelerate prompt")
	var unit = h.find_unit("jinx-demolitionist")
	assertions.assert_true(unit != null and unit.is_exhausted, "jinx enters exhausted without accelerate flag")


static func _test_hidden_unaffordable_play_not_legal(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["fight-or-flight"],
				"runes": [{"id": "chaos-rune", "exhausted": false}],
				"battlefield-a": ["chemtech-enforcer"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true(
		not ("play fight-or-flight" in moves),
		"hidden spell not playable with only 1E (costs 2E)",
	)
	assertions.assert_true(
		"hide fight-or-flight at battlefield-a" in moves,
		"hide offered at controlled battlefield-a",
	)
	assertions.assert_true(
		not ("hide fight-or-flight at battlefield-b" in moves),
		"hide not offered at uncontrolled battlefield-b",
	)


static func _test_hidden_hide_requires_any_power(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["fight-or-flight"],
				"runes": [],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true(
		not ("hide fight-or-flight at battlefield-a" in moves),
		"hide not offered without any payable hidden cost",
	)


static func _test_hidden_hide_auto_recycles_rune(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["fight-or-flight"],
				"runes": [{"id": "chaos-rune", "exhausted": false}],
				"battlefield-a": ["chemtech-enforcer"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var ps = h.gs().players[0]
	var rune_deck_before = ps.rune_deck.size()
	h.cmd(0, "hide fight-or-flight at battlefield-a")
	assertions.assert_no_error(h.controller, "hidden card hide succeeds with auto-recycled rune")
	assertions.assert_log_contains(h.controller, "[Auto] Rune recycled", "hide auto-recycles a rune for any power")
	assertions.assert_eq(ps.channeled_runes.size(), 0, "hidden cost recycles channeled rune")
	assertions.assert_eq(ps.rune_deck.size(), rune_deck_before + 1, "hidden cost returns rune to rune deck")
	assertions.assert_true(
		h.gs().board.battlefields[0].facedown_card != null,
		"hidden card placed face-down after paying cost",
	)


static func _test_hidden_hide_only_at_controlled_empty_facedown(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, 1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": ["fight-or-flight"],
				"runes": [],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var bf_a = h.gs().board.battlefields[0]
	var occupied_def = CardLoader.get_card("void-seeker")
	bf_a.facedown_card = CardInstance.new(occupied_def, "void-seeker-hidden", 0)
	bf_a.facedown_card.is_face_down = true
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true(
		not ("hide fight-or-flight at battlefield-a" in moves),
		"hide not offered when facedown slot occupied",
	)
	assertions.assert_true(
		not ("hide fight-or-flight at battlefield-b" in moves),
		"hide not offered at opponent-controlled battlefield-b",
	)


static func _test_hidden_hide_from_champion_zone(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": [],
				"runes": [{"id": "chaos-rune", "exhausted": false}],
				"battlefield-a": ["chemtech-enforcer"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var ps = h.gs().players[0]
	var hidden_def = CardLoader.get_card("fight-or-flight")
	ps.champion_zone = CardInstance.new(hidden_def, "fight-or-flight", 0)
	ps.champion_zone.location = "champion_zone"
	h.cmd(0, "hide fight-or-flight at battlefield-a")
	assertions.assert_no_error(h.controller, "hide from champion zone succeeds")
	assertions.assert_true(ps.champion_zone == null, "champion zone card moved when hidden")
	assertions.assert_true(
		h.gs().board.battlefields[0].facedown_card != null,
		"hidden card from champion zone placed facedown",
	)


static func _test_hidden_lost_control_trashes_facedown(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": [],
				"runes": [],
				"battlefield-a": ["chemtech-enforcer"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var bf = h.gs().board.battlefields[0]
	var hidden_def = CardLoader.get_card("fight-or-flight")
	bf.facedown_card = CardInstance.new(hidden_def, "fight-or-flight", 0)
	bf.facedown_card.is_face_down = true
	bf.facedown_card.hidden_turn_number = 1
	bf.controller_index = 1
	h.controller._run_cleanup()
	assertions.assert_true(bf.facedown_card == null, "lost-control cleanup removes hidden card")
	var in_trash := false
	for c in h.gs().players[0].trash:
		if c.instance_id == "fight-or-flight":
			in_trash = true
	assertions.assert_true(in_trash, "lost-control hidden card moved to owner trash")


static func _test_play_from_hidden_facedown_card(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "turn_number": 1, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": [],
				"runes": [],
				"battlefield-a": ["chemtech-enforcer"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{"deck_size": 10, "rune_deck_size": 12}
		]
	})
	var bf = h.gs().board.battlefields[0]
	var hidden_def = CardLoader.get_card("fight-or-flight")
	bf.facedown_card = CardInstance.new(hidden_def, "fight-or-flight", 0)
	bf.facedown_card.is_face_down = true
	bf.facedown_card.hidden_turn_number = 1
	var moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true(
		not ("play fight-or-flight from hidden" in moves),
		"facedown hidden card is not legal the same turn it was hidden",
	)
	h.gs().turn_number = 2
	h.gs().current_state = TurnStateMachine.State.NEUTRAL_CLOSED
	h.gs().priority_player_index = 0
	moves = LegalMoveEnumerator.enumerate(h.gs(), 0)
	assertions.assert_true(
		"play fight-or-flight from hidden" in moves,
		"facedown hidden card legal in later reaction window",
	)
	h.cmd(0, "play fight-or-flight from hidden")
	assertions.assert_no_error(h.controller, "play from hidden succeeds in reaction window")


static func _test_play_from_hidden_target_restricted_to_hidden_battlefield(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "turn_number": 2, "phase": "MAIN", "state": "NEUTRAL_CLOSED",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"battlefield_control": [0, -1],
		"players": [
			{
				"pool": {"energy": 0, "power": {}},
				"hand": [],
				"runes": [],
				"battlefield-a": ["chemtech-enforcer"],
				"deck_size": 10, "rune_deck_size": 12,
			},
			{
				"battlefield-b": ["flame-chompers"],
				"deck_size": 10, "rune_deck_size": 12
			}
		]
	})
	h.gs().priority_player_index = 0
	var bf = h.gs().board.battlefields[0]
	var hidden_def = CardLoader.get_card("fight-or-flight")
	bf.facedown_card = CardInstance.new(hidden_def, "fight-or-flight", 0)
	bf.facedown_card.is_face_down = true
	bf.facedown_card.hidden_turn_number = 1
	h.cmd(0, "play fight-or-flight from hidden target flame-chompers")
	assertions.assert_true(h.controller.last_command_error, "hidden spell rejects off-battlefield target")
	assertions.assert_log_contains(h.controller, "Invalid target", "hidden spell target rejection logged")
