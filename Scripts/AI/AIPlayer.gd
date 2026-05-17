class_name AIPlayer
extends Node

var controller: GameController
var player_index: int = 1

const THINK_DELAY: float = 0.6


func setup(gc: GameController, pi: int) -> void:
	controller = gc
	player_index = pi


func take_turn() -> void:
	if controller == null or controller.gs == null:
		return
	var gs = controller.gs
	if gs.game_over or gs.mulligan_phase:
		return
	if not gs.can_player_act(player_index):
		return
	# Delay slightly for readability
	await get_tree().create_timer(THINK_DELAY).timeout
	_decide_and_act()


func _decide_and_act() -> void:
	var gs = controller.gs
	if gs.game_over or not gs.can_player_act(player_index):
		return

	# Mulligan: always keep
	if gs.mulligan_phase and not gs.mulligan_done[player_index]:
		_submit("mulligan keep")
		return

	# If there's a pending prompt for us, choose the first valid option
	if not gs.pending_prompt.is_empty() and gs.pending_prompt.get("player_index", -1) == player_index:
		var choices = gs.pending_prompt.get("valid_choices", [])
		if not choices.is_empty():
			_submit("choose %s" % choices[0])
		else:
			_submit("choose none")
		return

	# Showdown/combat: pass
	if gs.is_showdown_state() and gs.focus_player_index == player_index:
		_submit("pass")
		return

	# Chain closed: pass
	if not gs.chain.is_empty():
		_submit("pass")
		return

	# Main Phase: tap all runes, play cards, move units, end turn
	if gs.current_phase == TurnStateMachine.Phase.MAIN and \
	   gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN and \
	   gs.turn_player_index == player_index:
		_do_main_phase()
		return

	# Default: end turn if it's ours
	if gs.turn_player_index == player_index:
		_submit("end turn")


func _do_main_phase() -> void:
	var gs = controller.gs
	var ps: PlayerState = gs.players[player_index]

	# Step 1: Tap all untapped runes for energy
	for i in range(ps.channeled_runes.size()):
		var rune = ps.channeled_runes[i]
		if not rune.is_exhausted:
			_submit("tap rune-%d" % i)
			await get_tree().create_timer(0.15).timeout
			if gs.game_over or not gs.can_player_act(player_index):
				return

	# Step 2: Play cards if we can afford them
	var played_something = true
	while played_something:
		played_something = false
		var best_card = _best_playable_card(gs, ps)
		if best_card != null:
			var target_bf = _choose_destination(gs, player_index)
			var cmd = "play %s" % best_card.instance_id
			if best_card.definition.card_type == "unit" and target_bf != "":
				cmd += " to %s" % target_bf
			_submit(cmd)
			await get_tree().create_timer(0.2).timeout
			played_something = true
			if gs.game_over or not gs.can_player_act(player_index):
				return

	# Step 3: Move ready units to unclaimed battlefields
	var ready_units = _get_ready_units_at_base(gs, player_index)
	for unit in ready_units:
		var target_bf = _best_move_target(gs, player_index)
		if target_bf != "":
			_submit("move %s to %s" % [unit.instance_id, target_bf])
			await get_tree().create_timer(0.2).timeout
			if gs.game_over or not gs.can_player_act(player_index):
				return

	# Step 4: End turn
	await get_tree().create_timer(0.1).timeout
	if gs.can_player_act(player_index) and gs.turn_player_index == player_index:
		_submit("end turn")


func _best_playable_card(gs: GameState, ps: PlayerState) -> CardInstance:
	var best: CardInstance = null
	var best_cost = -1
	for card in ps.hand:
		if card.definition.card_type == "rune":
			continue
		if card.definition.is_reaction:
			continue
		var cost = CostCalculator.compute_play_cost(card, player_index, gs)
		if CostCalculator.can_afford(player_index, cost, gs):
			var energy_cost = cost.get("energy", 0)
			if energy_cost > best_cost:
				best_cost = energy_cost
				best = card
	return best


func _choose_destination(gs: GameState, pi: int) -> String:
	# Prefer uncontrolled battlefields, then opponent-controlled
	for i in range(gs.board.battlefields.size()):
		var bf = gs.board.battlefields[i]
		if bf.controller_index == -1 and bf.units[1 - pi].is_empty():
			return bf.battlefield_id
	for i in range(gs.board.battlefields.size()):
		var bf = gs.board.battlefields[i]
		if bf.controller_index == 1 - pi:
			return bf.battlefield_id
	return ""


func _best_move_target(gs: GameState, pi: int) -> String:
	for i in range(gs.board.battlefields.size()):
		var bf = gs.board.battlefields[i]
		if bf.controller_index != pi and bf.units[pi].is_empty():
			return bf.battlefield_id
	return ""


func _get_ready_units_at_base(gs: GameState, pi: int) -> Array:
	var result: Array = []
	for u in gs.players[pi].get_units_at_base():
		if not u.is_exhausted:
			result.append(u)
	return result


func _submit(cmd: String) -> void:
	if controller and not controller.gs.game_over:
		controller.submit_command(player_index, cmd)
		controller.board_updated.emit()
