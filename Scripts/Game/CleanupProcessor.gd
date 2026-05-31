class_name CleanupProcessor

# Runs the 8-step cleanup sequence described in §17 of the implementation rules.
# Returns an array of log lines describing what happened.

static func run(gs: GameState, ability_resolver: AbilityResolver, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []

	# Step 1: Check win condition
	var winner = _check_win(gs)
	if winner >= 0:
		gs.game_over = true
		gs.winner_index = winner
		log_lines.append("> GAME OVER — P%d wins with %d points!" % [
			winner + 1, gs.players[winner].score
		])
		return log_lines

	# Step 2: Assign/Remove Attacker and Defender designations
	_update_combat_designations(gs)

	# Step 3a + 3b: Deathknell triggers then kill units with lethal damage
	var killed_lines = _process_deaths(gs, ability_resolver, controller)
	log_lines.append_array(killed_lines)

	# Step 4: Battlefields with no units in Open State → Uncontrolled
	if gs.is_open_state():
		for i in range(gs.board.battlefields.size()):
			var bf = gs.board.battlefields[i]
			var has_units = false
			for player_units in bf.units:
				if not player_units.is_empty():
					has_units = true
					break
			if not has_units and bf.controller_index >= 0:
				log_lines.append("> %s is now Uncontrolled" % bf.display_name)
				bf.controller_index = -1

	# Step 5: Recall unattached Gear at Battlefields to Base
	_recall_unattached_gear(gs, log_lines)

	# Step 6 & 7: Mark Contested battlefields as Staged Showdowns or Combats
	_mark_staged(gs, log_lines)

	# Step 8: If Neutral Open and there are staged combats/showdowns, prompt turn player to start one
	if gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN:
		if not gs.board.staged_combats.is_empty() or not gs.board.staged_showdowns.is_empty():
			log_lines.append_array(_prompt_staged(gs, controller))

	return log_lines


static func _check_win(gs: GameState) -> int:
	if gs.victory_score <= 0:
		return -1
	var max_score = -1
	var leader = -1
	for i in range(gs.players.size()):
		if gs.players[i].score > max_score:
			max_score = gs.players[i].score
			leader = i
	if max_score >= gs.victory_score:
		# Verify leader has more than all others
		var others_all_less = true
		for i in range(gs.players.size()):
			if i != leader and gs.players[i].score >= max_score:
				others_all_less = false
				break
		if others_all_less:
			return leader
	return -1


static func _update_combat_designations(gs: GameState) -> void:
	for bf in gs.board.battlefields:
		var p0_has = not bf.units[0].is_empty()
		var p1_has = not bf.units[1].is_empty()
		var in_combat = p0_has and p1_has
		for pi in range(bf.units.size()):
			for u in bf.units[pi]:
				u.is_attacker = in_combat and (pi == gs.attacker_player_index if gs.combat_bf_index >= 0 else false)
				u.is_defender = in_combat and (pi != gs.attacker_player_index if gs.combat_bf_index >= 0 else false)


static func _process_deaths(gs: GameState, ability_resolver: AbilityResolver, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	var units_to_kill: Array = []

	for ps in gs.players:
		for u in ps.get_units_at_base():
			if u.has_lethal_damage():
				units_to_kill.append(u)
	for bf in gs.board.battlefields:
		for player_units in bf.units:
			for u in Array(player_units):
				if u.has_lethal_damage():
					units_to_kill.append(u)

	for u in units_to_kill:
		for ab in u.definition.abilities:
			if ab.get("timing", "") == "on_death":
				var dk_line = "> %s Deathknell triggers" % u.display_name()
				log_lines.append(dk_line)
				if controller != null:
					controller.log_lines.append(dk_line)
				var ctx = {"player_index": u.owner_index, "controller": controller}
				var ab_lines = ability_resolver.resolve_ability(ab, u, null, gs, ctx)
				log_lines.append_array(ab_lines)
				if controller != null:
					for line in ab_lines:
						controller.log_lines.append(line)

	for u in units_to_kill:
		log_lines.append("> %s (P%d) was killed" % [u.display_name(), u.owner_index + 1])
		gs.board.remove_unit_from_battlefield(u)
		var owner_ps: PlayerState = gs.players[u.owner_index]
		owner_ps.move_to_trash(u)

	return log_lines


static func _recall_unattached_gear(gs: GameState, log_lines: Array) -> void:
	for pi in range(gs.players.size()):
		var ps: PlayerState = gs.players[pi]
		for gear in Array(ps.base_permanents):
			if gear.definition.card_type != "gear":
				continue
			if gear.is_at_battlefield() and gear.attached_to == null:
				gs.board.remove_unit_from_battlefield(gear)
				gear.location = "base"
				log_lines.append("> %s recalled to P%d base" % [gear.display_name(), pi + 1])


static func _mark_staged(gs: GameState, log_lines: Array) -> void:
	gs.board.staged_showdowns.clear()
	gs.board.staged_combats.clear()
	for i in range(gs.board.battlefields.size()):
		var bf = gs.board.battlefields[i]
		if not bf.is_contested:
			continue
		var p0_has = not bf.units[0].is_empty()
		var p1_has = not bf.units[1].is_empty()
		if p0_has and p1_has:
			if not i in gs.board.staged_combats:
				gs.board.staged_combats.append(i)
				log_lines.append("> Combat staged at %s" % bf.display_name)
		elif p0_has or p1_has:
			if not i in gs.board.staged_showdowns:
				gs.board.staged_showdowns.append(i)
				log_lines.append("> Showdown staged at %s" % bf.display_name)


static func _prompt_staged(gs: GameState, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	var total_staged = gs.board.staged_combats.size() + gs.board.staged_showdowns.size()
	if total_staged > 1:
		var choices: Array = []
		for idx in gs.board.staged_combats:
			choices.append(gs.board.battlefields[idx].battlefield_id)
		for idx in gs.board.staged_showdowns:
			var bid = gs.board.battlefields[idx].battlefield_id
			if not bid in choices:
				choices.append(bid)
		gs.pending_prompt = {
			"player_index": gs.turn_player_index,
			"type": "choose_battlefield",
			"valid_choices": choices,
			"prompt": "[PROMPT] Choose battlefield to resolve — use: choose <id>",
		}
		log_lines.append(gs.pending_prompt["prompt"])
		return log_lines

	if not gs.board.staged_combats.is_empty():
		var bf_idx = gs.board.staged_combats[0]
		gs.board.staged_combats.erase(bf_idx)
		gs.board.staged_showdowns.erase(bf_idx)
		gs.board.battlefields[bf_idx].is_contested = false
		log_lines.append_array(CombatProcessor.begin_combat(
			bf_idx,
			gs.attacker_player_index if gs.attacker_player_index >= 0 else gs.turn_player_index,
			gs,
			controller
		))
	elif not gs.board.staged_showdowns.is_empty():
		var bf_idx = gs.board.staged_showdowns[0]
		gs.board.staged_showdowns.erase(bf_idx)
		gs.board.battlefields[bf_idx].is_contested = false
		log_lines.append_array(ShowdownProcessor.begin_showdown(bf_idx, gs.turn_player_index, gs))
	return log_lines


static func heal_all_units(gs: GameState) -> void:
	for ps in gs.players:
		for u in ps.get_units_at_base():
			u.heal_all()
	for bf in gs.board.battlefields:
		for player_units in bf.units:
			for u in player_units:
				u.heal_all()


static func expire_turn_effects(gs: GameState) -> void:
	for ps in gs.players:
		for u in ps.get_units_at_base():
			u.clear_temp_effects()
		for u in gs.board.get_all_units_on_board(ps.player_index):
			u.clear_temp_effects()
		ps.reset_turn_state()
