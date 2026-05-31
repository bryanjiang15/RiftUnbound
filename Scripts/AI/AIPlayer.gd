class_name AIPlayer
extends Node

# AI player that sends the current game state to the Python agent service and
# executes whatever command the agent returns.  Falls back to the built-in
# heuristic when the service is unreachable or returns an error.
#
# The node must be named "AIPlayer" (GameController looks it up by that name).
# GameScene wires it up via: _ai.setup(_controller, 1)

var controller: GameController
var player_index: int = 1

const AGENT_URL := "http://localhost:8765/decision"
const THINK_DELAY := 0.5       # seconds before each decision
const HTTP_TIMEOUT := 8.0      # seconds before falling back to heuristic
const MAX_RETRIES := 3         # max rejection retry attempts

var _http: HTTPRequest = null
var _pending_brief_state: Dictionary = {}
var _retry_count: int = 0
var _last_rejected_move: Dictionary = {}
var _last_rejection_reason: String = ""
var _waiting_for_http: bool = false

# Phase 1 additions
var _current_game_id: String = ""
var _game_over_reported: bool = false


func setup(gc: GameController, pi: int) -> void:
	controller = gc
	player_index = pi
	_http = HTTPRequest.new()
	_http.timeout = HTTP_TIMEOUT
	add_child(_http)
	_http.request_completed.connect(_on_request_completed)
	# Phase 1: detect game-over and opponent actions
	controller.board_updated.connect(_on_board_updated)
	controller.game_log_message.connect(_on_game_log_message)


func take_turn() -> void:
	if controller == null or controller.gs == null:
		return
	var gs = controller.gs
	if gs.game_over:
		return
	if _waiting_for_http:
		return

	# Delay slightly so the game log is readable
	await get_tree().create_timer(THINK_DELAY).timeout
	if gs.game_over:
		return

	# Re-check that the AI can still act (state may have changed during delay)
	var can_act := _can_act_now(gs)
	if not can_act:
		return

	_retry_count = 0
	_last_rejected_move = {}
	_last_rejection_reason = ""
	await _request_decision(gs)


# ── HTTP request ──────────────────────────────────────────────────────────────

func _request_decision(gs: GameState) -> void:
	_pending_brief_state = BriefStateSerializer.serialize(gs, player_index)
	_current_game_id = _pending_brief_state.get("game_id", "")

	var payload := JSON.stringify(_build_request_payload())
	var headers := PackedStringArray(["Content-Type: application/json"])

	var err = _http.request(AGENT_URL, headers, HTTPClient.METHOD_POST, payload)
	if err != OK:
		push_warning("AIPlayer: HTTPRequest failed to start (err=%d). Using heuristic." % err)
		_heuristic_fallback(gs)
		return

	_waiting_for_http = true


func _build_request_payload() -> Dictionary:
	var payload := {
		"brief_state": _pending_brief_state,
		"game_id": _pending_brief_state.get("game_id", "game"),
	}
	if not _last_rejected_move.is_empty():
		payload["rejection_context"] = {
			"rejected_move": _last_rejected_move,
			"rejection_reason": _last_rejection_reason,
		}
	return payload


func _on_request_completed(result: int, response_code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_waiting_for_http = false
	var gs = controller.gs if controller else null
	if gs == null or gs.game_over:
		return

	if result != HTTPRequest.RESULT_SUCCESS or response_code != 200:
		push_warning("AIPlayer: HTTP error (result=%d, code=%d). Using heuristic." % [result, response_code])
		_heuristic_fallback(gs)
		return

	var text := body.get_string_from_utf8()
	var parsed = JSON.parse_string(text)
	if parsed == null or not parsed is Dictionary:
		push_warning("AIPlayer: Invalid JSON response. Using heuristic.")
		_heuristic_fallback(gs)
		return

	var decision: Dictionary = parsed
	var move_dict: Dictionary = decision.get("move", {})
	if move_dict.is_empty():
		push_warning("AIPlayer: No 'move' in response. Using heuristic.")
		_heuristic_fallback(gs)
		return

	var cmd := _move_to_command(move_dict)
	if cmd.is_empty():
		push_warning("AIPlayer: Could not translate move to command. Using heuristic.")
		_heuristic_fallback(gs)
		return

	# Store decision for potential rejection context on next call
	_last_rejected_move = move_dict

	# Submit the command.  submit_command sets controller.last_command_error if it
	# produced an [ERROR] log, letting us distinguish real rejections from normal
	# "still my turn" situations.
	_submit(cmd)

	# Rejection detected: retry immediately (synchronously, before any deferred
	# _trigger_ai_turn fires) so _waiting_for_http is set before the next take_turn().
	if controller.last_command_error:
		_last_rejection_reason = "Game engine rejected the command."
		_report_outcome(false, _last_rejection_reason)
		if _retry_count < MAX_RETRIES:
			_retry_count += 1
			push_warning("AIPlayer: Move rejected — retry %d/%d" % [_retry_count, MAX_RETRIES])
			_request_decision(gs)  # synchronous; sets _waiting_for_http = true
		else:
			push_warning("AIPlayer: Exhausted %d retries — heuristic fallback." % MAX_RETRIES)
			_heuristic_fallback(gs)
	else:
		_report_outcome(true)
	# If the move was accepted the normal _maybe_trigger_ai() → take_turn() cycle
	# (triggered inside submit_command) handles the next decision.  No extra work needed.


# ── Command translation ───────────────────────────────────────────────────────

func _move_to_command(move: Dictionary) -> String:
	var action: String = move.get("action", "")
	var p: Dictionary = move.get("parameters", {})

	match action:
		"mulligan_keep":
			return "mulligan keep"
		"mulligan":
			var ids := " ".join(p.get("card_ids", []))
			return ("mulligan %s" % ids) if ids != "" else "mulligan keep"
		"play_card":
			var cmd := "play %s" % p.get("card_id", "")
			if p.get("destination", "") != "":
				cmd += " to %s" % p["destination"]
			if p.get("target_id", "") != "":
				cmd += " target %s" % p["target_id"]
			if p.get("from_champion", false):
				cmd += " from champion"
			if p.get("from_hidden", false):
				cmd += " from hidden"
			if p.get("accelerate", false):
				cmd += " accelerate"
			return cmd
		"move_unit":
			var ids = p.get("unit_ids", [])
			if ids is String:
				ids = [ids]
			return "move %s to %s" % [" ".join(ids), p.get("destination", "base")]
		"pass":
			return "pass"
		"end_turn":
			return "end turn"
		"use_ability":
			var cmd := "use %s" % p.get("card_id", "")
			if p.get("target_id", "") != "":
				cmd += " target %s" % p["target_id"]
			return cmd
		"react":
			var cmd := "react %s" % p.get("card_id", "")
			if p.get("target_id", "") != "":
				cmd += " target %s" % p["target_id"]
			return cmd
		"assign_damage":
			return "assign %d to %s" % [p.get("amount", 0), p.get("target_id", "")]
		"assign_done":
			return "assign done"
		"choose":
			return "choose %s" % p.get("target_id", "")
		"choose_none":
			return "choose none"
		_:
			return ""


# ── Heuristic fallback ────────────────────────────────────────────────────────

func _heuristic_fallback(gs: GameState) -> void:
	if gs.game_over or not _can_act_now(gs):
		return

	# Mulligan: always keep
	if gs.mulligan_phase and not gs.mulligan_done[player_index]:
		_submit("mulligan keep")
		return

	# Pending prompt: pick first option
	if not gs.pending_prompt.is_empty() and \
	   gs.pending_prompt.get("player_index", -1) == player_index:
		var choices = gs.pending_prompt.get("valid_choices", [])
		_submit("choose %s" % choices[0] if not choices.is_empty() else "choose none")
		return

	# Showdown / chain: pass
	if gs.is_showdown_state() and gs.focus_player_index == player_index:
		_submit("pass")
		return
	if not gs.chain.is_empty():
		_submit("pass")
		return

	# Combat damage assignment: assign everything to first unit and confirm
	if gs.combat_assignment_active and gs.attacker_player_index == player_index:
		if gs.combat_bf_index >= 0:
			var bf = gs.board.battlefields[gs.combat_bf_index]
			var defenders = bf.units[1 - player_index]
			var remaining = gs.remaining_attacker_might
			for unit in defenders:
				if unit.instance_id not in gs.damage_assignments and remaining > 0:
					_submit("assign %d to %s" % [remaining, unit.instance_id])
					await get_tree().create_timer(0.1).timeout
					remaining = 0
		_submit("assign done")
		return

	# Main phase
	if gs.current_phase == TurnStateMachine.Phase.MAIN and \
	   gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN and \
	   gs.turn_player_index == player_index:
		await _heuristic_main_phase(gs)
		return

	if gs.turn_player_index == player_index:
		_submit("end turn")


func _heuristic_main_phase(gs: GameState) -> void:
	var ps: PlayerState = gs.players[player_index]

	# Play highest-cost affordable card (runes auto-pay on play)
	var played := true
	while played:
		played = false
		var best := _best_playable_card(gs, ps)
		if best != null:
			var dest := _choose_destination(gs)
			var cmd := "play %s" % best.instance_id
			if best.definition.card_type == "unit" and dest != "":
				cmd += " to %s" % dest
			_submit(cmd)
			await get_tree().create_timer(0.2).timeout
			played = true
			if gs.game_over or not _can_act_now(gs):
				return

	# Move ready base units toward objectives
	for unit in _get_ready_units_at_base(gs):
		var target := _best_move_target(gs)
		if target != "":
			_submit("move %s to %s" % [unit.instance_id, target])
			await get_tree().create_timer(0.2).timeout
			if gs.game_over or not _can_act_now(gs):
				return

	await get_tree().create_timer(0.1).timeout
	if _can_act_now(gs) and gs.turn_player_index == player_index:
		_submit("end turn")


func _best_playable_card(gs: GameState, ps: PlayerState) -> CardInstance:
	var best: CardInstance = null
	var best_cost := -1
	for card in ps.hand:
		if card.definition.card_type == "rune" or card.definition.is_reaction:
			continue
		var cost = CostCalculator.compute_play_cost(card, player_index, gs)
		if CostCalculator.can_afford(player_index, cost, gs):
			var ec: int = cost.get("energy", 0)
			if ec > best_cost:
				best_cost = ec
				best = card
	return best


func _choose_destination(gs: GameState) -> String:
	for bf in gs.board.battlefields:
		if bf.controller_index == -1 and bf.units[1 - player_index].is_empty():
			return bf.battlefield_id
	for bf in gs.board.battlefields:
		if bf.controller_index == 1 - player_index:
			return bf.battlefield_id
	return ""


func _best_move_target(gs: GameState) -> String:
	for bf in gs.board.battlefields:
		if bf.controller_index != player_index and bf.units[player_index].is_empty():
			return bf.battlefield_id
	return ""


func _get_ready_units_at_base(gs: GameState) -> Array:
	var result: Array = []
	for u in gs.players[player_index].get_units_at_base():
		if not u.is_exhausted:
			result.append(u)
	return result


# ── Helpers ───────────────────────────────────────────────────────────────────

func _can_act_now(gs: GameState) -> bool:
	if gs.mulligan_phase:
		return not gs.mulligan_done[player_index]
	return gs.can_player_act(player_index)


func _submit(cmd: String) -> void:
	if controller and not controller.gs.game_over:
		controller.submit_command(player_index, cmd)
		controller.board_updated.emit()


# ── Phase 1: outcome reporting, game-over, opponent tracking ──────────────────

func _report_outcome(accepted: bool, rejection_reason: String = "") -> void:
	if _current_game_id.is_empty():
		return
	var body := {
		"game_id": _current_game_id,
		"accepted": accepted,
	}
	if not accepted and not rejection_reason.is_empty():
		body["rejection_reason"] = rejection_reason
	_fire_and_forget(AGENT_URL.replace("/decision", "/outcome"), body)


func _on_board_updated() -> void:
	if _game_over_reported or controller == null or controller.gs == null:
		return
	var gs = controller.gs
	if not gs.game_over or gs.winner_index < 0:
		return
	_game_over_reported = true
	var body := {
		"game_id": _current_game_id,
		"winner_index": gs.winner_index,
		"my_player_index": player_index,
		"my_score": gs.players[player_index].score,
		"opp_score": gs.players[1 - player_index].score,
		"total_turns": gs.turn_number,
	}
	_fire_and_forget(AGENT_URL.replace("/decision", "/game_over"), body)


func _on_game_log_message(text: String) -> void:
	# Detect visible opponent commands in the format "[P{n}] > {command}"
	var opp_index := 1 - player_index
	var prefix := "[P%d] > " % (opp_index + 1)
	if not text.begins_with(prefix):
		return
	var cmd := text.substr(prefix.length()).strip_edges()
	var description := _parse_opponent_command(cmd)
	if description.is_empty() or _current_game_id.is_empty():
		return
	var turn := controller.gs.turn_number if controller and controller.gs else 0
	_fire_and_forget(AGENT_URL.replace("/decision", "/opponent_action"), {
		"game_id": _current_game_id,
		"turn": turn,
		"action": description,
	})


func _parse_opponent_command(cmd: String) -> String:
	var tokens := cmd.split(" ", false)
	if tokens.is_empty():
		return ""
	match tokens[0]:
		"play":
			if tokens.size() < 2:
				return ""
			var card_id := tokens[1]
			var dest := ""
			var to_idx := tokens.find("to")
			if to_idx >= 0 and to_idx + 1 < tokens.size():
				dest = tokens[to_idx + 1]
			return "played %s%s" % [card_id, (" to " + dest) if dest else ""]
		"move":
			var to_idx := tokens.find("to")
			if to_idx < 0 or to_idx + 1 >= tokens.size():
				return ""
			var dest := tokens[to_idx + 1]
			var unit_count := to_idx - 1
			var label := "unit" if unit_count <= 1 else "%d units" % unit_count
			return "moved %s to %s" % [label, dest]
		"end":
			return "ended their turn"
		"pass":
			return "passed"
		"use":
			if tokens.size() < 2:
				return ""
			return "used ability %s%s" % [tokens[1], _target_suffix(tokens)]
		"react":
			if tokens.size() < 2:
				return ""
			return "played reaction %s%s" % [tokens[1], _target_suffix(tokens)]
		"choose":
			if tokens.size() < 2:
				return ""
			return "chose %s" % tokens[1]
		_:
			return ""


func _target_suffix(tokens: Array) -> String:
	var target_idx := tokens.find("target")
	if target_idx >= 0 and target_idx + 1 < tokens.size():
		return " targeting %s" % tokens[target_idx + 1]
	return ""


func _fire_and_forget(url: String, body: Dictionary) -> void:
	var http := HTTPRequest.new()
	add_child(http)
	http.request_completed.connect(func(_r, _c, _h, _b): http.queue_free())
	http.request(url, ["Content-Type: application/json"],
		HTTPClient.METHOD_POST, JSON.stringify(body))
