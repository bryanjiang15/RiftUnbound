class_name ShowdownProcessor

static func begin_showdown(bf_index: int, focus_player: int, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	gs.board.active_showdown_bf = bf_index
	gs.board.battlefields[bf_index].is_contested = false
	gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
	gs.focus_player_index = focus_player
	gs.passes_in_sequence = 0
	var bf_name = gs.board.battlefields[bf_index].display_name
	log_lines.append("> Non-combat Showdown begins at %s (P%d has Focus)" % [bf_name, focus_player + 1])
	log_lines.append("[PROMPT] P%d: play Action/Reaction card or 'pass'" % (focus_player + 1))
	return log_lines


static func handle_pass(gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var passer = gs.focus_player_index
	log_lines.append("> [P%d] Passed Focus" % (passer + 1))
	gs.passes_in_sequence += 1

	if gs.passes_in_sequence >= gs.players.size():
		return close_showdown(gs)
	else:
		gs.focus_player_index = (gs.focus_player_index + 1) % gs.players.size()
		log_lines.append("[PROMPT] P%d: play Action/Reaction card or 'pass'" % (gs.focus_player_index + 1))
	return log_lines


static func close_showdown(gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var bf_index = gs.board.active_showdown_bf
	gs.board.active_showdown_bf = -1
	gs.current_state = TurnStateMachine.State.NEUTRAL_OPEN
	gs.focus_player_index = -1
	gs.passes_in_sequence = 0

	if bf_index < 0:
		return log_lines

	var bf = gs.board.battlefields[bf_index]
	var bf_name = bf.display_name

	var p0_has = not bf.units[0].is_empty()
	var p1_has = not bf.units[1].is_empty()

	if p0_has and not p1_has:
		log_lines.append_array(establish_control(gs, bf_index, 0, true))
	elif p1_has and not p0_has:
		log_lines.append_array(establish_control(gs, bf_index, 1, true))
	else:
		log_lines.append("> Showdown at %s concluded with no change" % bf_name)

	log_lines.append("> Showdown at %s ended — back to Neutral Open" % bf_name)
	return log_lines


static func establish_control(gs: GameState, bf_index: int, player_index: int, is_conquer: bool, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	var bf = gs.board.battlefields[bf_index]
	var was_controlled_by_opponent = bf.controller_index >= 0 and bf.controller_index != player_index
	var previously_uncontrolled = bf.controller_index == -1

	bf.controller_index = player_index
	var ps: PlayerState = gs.players[player_index]
	var bf_name = bf.display_name

	if previously_uncontrolled or was_controlled_by_opponent:
		log_lines.append("> P%d conquered %s!" % [player_index + 1, bf_name])
		if is_conquer and not bf_index in ps.battlefields_scored_this_turn:
			var scored = _apply_conquer_score(gs, player_index, bf_index)
			if scored:
				log_lines.append("> P%d scored 1 point (Conquer). Score: P1=%d, P2=%d" % [
					player_index + 1, gs.players[0].score, gs.players[1].score
				])
			else:
				var drawn = ps.draw_card()
				if drawn:
					log_lines.append("> P%d draws instead of Conquer point (Winning Point rule)" % (player_index + 1))
		if controller != null and (previously_uncontrolled or was_controlled_by_opponent):
			for line in controller.trigger_dispatcher.emit("on_conquer", {
				"battlefield_index": bf_index,
				"player_index": player_index,
				"controller": controller,
			}, gs, controller):
				log_lines.append(line)
				controller.log_lines.append(line)
	else:
		log_lines.append("> P%d holds %s" % [player_index + 1, bf_name])

	return log_lines


static func _apply_conquer_score(gs: GameState, player_index: int, bf_index: int) -> bool:
	var ps = gs.players[player_index]
	ps.battlefields_scored_this_turn.append(bf_index)

	var would_win = ps.score + 1 >= gs.victory_score
	var all_bfs_scored = ps.battlefields_scored_this_turn.size() >= gs.board.battlefields.size()

	if would_win and not all_bfs_scored:
		return false

	ps.score += 1
	return true
