class_name RuleShowdownTests
extends RefCounted

const TcgTestHarness = preload("res://Scripts/Tests/Tcg/TcgTestHarness.gd")
const LegalMoveEnumerator = preload("res://Scripts/AI/LegalMoveEnumerator.gd")

static func run(assertions) -> void:
	_test_showdown_establishes_control(assertions)
	_test_conquer_trigger_fires_after_showdown_close(assertions)
	_test_showdown_waits_for_pending_discard(assertions)
	_test_p2_can_act_after_showdown_focus_pass(assertions)
	_test_p2_cannot_act_while_p1_has_focus(assertions)
	_test_showdown_chain_priority_not_focus(assertions)
	_test_reaction_playable_in_showdown_open(assertions)
	_test_end_turn_blocked_with_pending_choice(assertions)
	_test_stale_pending_cleared_for_new_turn_player(assertions)


static func _test_showdown_establishes_control(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"battlefield-a": [{"id": "vi-destructive", "owner": 0}], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().board.active_showdown_bf = 0
	var lines = ShowdownProcessor.close_showdown(h.gs())
	assertions.assert_eq(h.gs().board.battlefields[0].controller_index, 0, "showdown establishes control")


static func _test_conquer_trigger_fires_after_showdown_close(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0,
		"phase": "MAIN",
		"state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"base": [{"id": "chemtech-enforcer", "exhausted": false}],
				"runes": [
					{"id": "fury-rune", "exhausted": true},
					{"id": "fury-rune", "exhausted": true},
				],
				"deck_size": 5,
				"rune_deck_size": 12,
			},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.cmd(0, "move chemtech-enforcer to battlefield-b")
	h.cmd(0, "pass")
	h.cmd(1, "pass")
	assertions.assert_log_contains(
		h.controller,
		"Scheduled ready_runes at end of turn",
		"targons peak schedules ready runes after showdown conquer",
	)
	h.cmd(0, "end turn")
	assertions.assert_true(
		not h.gs().players[0].channeled_runes[0].is_exhausted,
		"targons peak readies first rune at end of turn",
	)
	assertions.assert_true(
		not h.gs().players[0].channeled_runes[1].is_exhausted,
		"targons peak readies second rune at end of turn",
	)


static func _test_showdown_waits_for_pending_discard(assertions) -> void:
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
	h.controller.submit_command(0, "move traveling-merchant to battlefield-a")
	assertions.assert_eq(h.gs().pending_prompt.get("type", ""), "choose_discard",
		"move discard prompt is pending")
	assertions.assert_true(h.gs().board.staged_showdowns.size() > 0, "showdown is staged")
	assertions.assert_true(not h.gs().is_showdown_state(), "showdown waits for discard choice")


static func _test_p2_can_act_after_showdown_focus_pass(assertions) -> void:
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
	assertions.assert_true(h.gs().is_showdown_state(), "showdown begins after discard")
	h.cmd(0, "pass")
	assertions.assert_true(h.gs().can_player_act(1), "p2 can act when showdown focus passes")
	h.cmd(1, "pass")
	assertions.assert_true(not h.gs().is_showdown_state(), "showdown closes after both pass")


static func _showdown_fixture_harness() -> TcgTestHarness:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"base": [{"id": "traveling-merchant", "exhausted": false}],
				"hand": ["void-seeker", "fury-rune"],
				"pool": {"energy": 5, "power": {"fury": 1}},
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"deck_size": 5, "rune_deck_size": 12
			},
			{
				"deck_size": 5, "rune_deck_size": 12
			}
		]
	})
	h.cmd_with_choices(0, "move traveling-merchant to battlefield-a", ["fury-rune"])
	return h


static func _test_p2_cannot_act_while_p1_has_focus(assertions) -> void:
	var h = _showdown_fixture_harness()
	assertions.assert_eq(h.gs().focus_player_index, 0, "p1 holds focus")
	assertions.assert_eq(h.gs().current_state, TurnStateMachine.State.SHOWDOWN_OPEN,
		"showdown is open")
	assertions.assert_false(h.gs().can_player_act(1), "p2 cannot act while p1 has focus")
	assertions.assert_eq(LegalMoveEnumerator.enumerate(h.gs(), 1).size(), 0,
		"p2 has no legal moves without focus")


static func _test_showdown_chain_priority_not_focus(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "SHOWDOWN_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"hand": ["void-seeker"],
				"pool": {"energy": 5, "power": {"fury": 1}},
				"runes": [{"id": "fury-rune", "exhausted": false}],
				"deck_size": 5, "rune_deck_size": 12
			},
			{
				"battlefield-a": [{"id": "blazing-scorcher", "owner": 1}],
				"deck_size": 5, "rune_deck_size": 12
			}
		]
	})
	var gs = h.gs()
	gs.focus_player_index = 0
	gs.board.active_showdown_bf = 0
	assertions.assert_eq(gs.focus_player_index, 0, "p1 holds focus before action")
	h.controller.submit_command(0, "play void-seeker target blazing-scorcher")
	assertions.assert_no_error(h.controller, "p1 plays action in showdown")
	assertions.assert_true(h.gs().is_closed_chain_state(), "chain active in showdown closed")
	assertions.assert_eq(h.gs().priority_player_index, 1, "chain priority passes to p2")
	assertions.assert_eq(h.gs().focus_player_index, 0, "focus stays with p1 during chain")
	assertions.assert_false(h.gs().can_player_act(0), "p1 cannot act on chain without priority")
	assertions.assert_true(h.gs().can_player_act(1), "p2 has chain priority")
	var p2_moves: Array = LegalMoveEnumerator.enumerate(h.gs(), 1)
	assertions.assert_true("pass" in p2_moves, "p2 may pass on chain")
	assertions.assert_eq(LegalMoveEnumerator.enumerate(h.gs(), 0).size(), 0,
		"p1 has no legal moves while waiting on chain priority")

	h.controller.submit_command(0, "pass")
	assertions.assert_true(h.controller.last_command_error,
		"p1 cannot pass chain without priority")

	h.controller.submit_command(1, "pass")
	assertions.assert_no_error(h.controller, "p2 passes on chain")
	assertions.assert_eq(h.gs().priority_player_index, 0,
		"chain priority returns to p1 after p2 passes")
	assertions.assert_false(h.gs().chain.is_empty(),
		"chain waits for p1 pass before resolving")


static func _test_reaction_playable_in_showdown_open(assertions) -> void:
	var h = TcgTestHarness.new()
	var fixture = {
		"first_player": 0, "phase": "MAIN", "state": "SHOWDOWN_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{
				"hand": ["gust"],
				"pool": {"energy": 1},
				"deck_size": 5,
				"rune_deck_size": 12
			},
			{
				"battlefield-a": [{"id": "flame-chompers", "owner": 1}],
				"deck_size": 5,
				"rune_deck_size": 12
			}
		]
	}
	h.load_fixture_dict(fixture)
	h.gs().focus_player_index = 0
	h.gs().board.active_showdown_bf = 0
	h.controller.submit_command(0, "play gust target flame-chompers")
	assertions.assert_no_error(h.controller, "reaction playable in showdown open")
	assertions.assert_true(h.gs().is_closed_chain_state(),
		"reaction creates chain from showdown open")
	assertions.assert_eq(h.gs().priority_player_index, 1,
		"reaction passes chain priority to opponent")

	var h2 = TcgTestHarness.new()
	h2.load_fixture_dict(fixture)
	h2.gs().focus_player_index = 0
	h2.gs().board.active_showdown_bf = 0
	assertions.assert_true("react gust target flame-chompers" in LegalMoveEnumerator.enumerate(h2.gs(), 0),
		"reaction is enumerated in showdown open")
	h2.controller.submit_command(0, "react gust target flame-chompers")
	assertions.assert_no_error(h2.controller, "react command works in showdown open")
	assertions.assert_true(h2.gs().is_closed_chain_state(),
		"react command closes showdown while chain is pending")
	assertions.assert_true("pass" in LegalMoveEnumerator.enumerate(h2.gs(), 1),
		"opponent can pass after showdown reaction")
	h2.controller.submit_command(0, "pass")
	assertions.assert_true(h2.controller.last_command_error,
		"focus player cannot pass while opponent has chain priority")
	h2.controller.submit_command(1, "pass")
	assertions.assert_no_error(h2.controller, "opponent passes after showdown reaction")
	assertions.assert_eq(h2.gs().priority_player_index, 0,
		"chain priority returns after opponent pass")

	var h3 = TcgTestHarness.new()
	h3.load_fixture_dict(fixture)
	h3.gs().focus_player_index = 1
	h3.gs().priority_player_index = 0
	h3.gs().board.active_showdown_bf = 0
	h3.controller.submit_command(0, "react gust target flame-chompers")
	assertions.assert_true(h3.controller.last_command_error,
		"non-focus player cannot react in showdown open")


static func _test_end_turn_blocked_with_pending_choice(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"hand": ["void-seeker", "fury-rune"], "deck_size": 5, "rune_deck_size": 12},
			{"deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().pending_prompt = {
		"player_index": 0,
		"type": "choose_discard",
		"valid_choices": ["void-seeker", "fury-rune"],
		"prompt": "[PROMPT] Choose a card to discard",
	}
	h.controller.submit_command(0, "end turn")
	assertions.assert_true(h.controller.last_command_error,
		"end turn blocked while pending choice unresolved")
	h.controller.submit_command(0, "play void-seeker")
	assertions.assert_true(h.controller.last_command_error,
		"other commands blocked while pending choice unresolved")


static func _test_stale_pending_cleared_for_new_turn_player(assertions) -> void:
	var h = TcgTestHarness.new()
	h.load_fixture_dict({
		"first_player": 0, "turn_number": 6, "phase": "MAIN", "state": "NEUTRAL_OPEN",
		"battlefields": ["zaun-warrens", "targons-peak"],
		"players": [
			{"deck_size": 5, "rune_deck_size": 12},
			{"hand": ["fight-or-flight"], "deck_size": 5, "rune_deck_size": 12}
		]
	})
	h.gs().turn_player_index = 1
	h.gs().pending_prompt = {
		"player_index": 0,
		"type": "choose_discard",
		"valid_choices": ["void-seeker"],
		"prompt": "[PROMPT] Choose a card to discard",
	}
	h.controller._execute_start_of_turn()
	assertions.assert_true(h.gs().pending_prompt.is_empty(),
		"stale pending choice cleared for new turn player")
	assertions.assert_true(h.gs().can_player_act(1),
		"p2 can act after stale prompt cleared")
	assertions.assert_true(not LegalMoveEnumerator.enumerate(h.gs(), 1).is_empty(),
		"p2 has legal moves at start of turn")
