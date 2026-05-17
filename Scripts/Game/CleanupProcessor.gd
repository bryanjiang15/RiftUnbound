class_name CleanupProcessor

# Runs the 8-step cleanup sequence described in §17 of the implementation rules.
# Returns an array of log lines describing what happened.

static func run(gs: GameState, ability_resolver: AbilityResolver) -> Array:
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
	var killed_lines = _process_deaths(gs, ability_resolver)
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
			log_lines.append_array(_prompt_staged(gs))

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


static func _process_deaths(gs: GameState, ability_resolver: AbilityResolver) -> Array:
	var log_lines: Array[String] = []
	var units_to_kill: Array = []

	# Collect all units with lethal damage
	for ps in gs.players:
		for u in ps.get_units_at_base():
			if u.has_lethal_damage():
				units_to_kill.append(u)
	for bf in gs.board.battlefields:
		for player_units in bf.units:
			for u in Array(player_units):
				if u.has_lethal_damage():
					units_to_kill.append(u)

	# Fire Deathknell before removing
	for u in units_to_kill:
		if u.has_keyword("deathknell"):
			log_lines.append("> %s Deathknell triggers" % u.display_name())
			for ab in u.definition.abilities:
				if ab.get("timing", "") == "on_death":
					var ab_lines = ability_resolver.resolve_ability(ab, u, null, gs)
					log_lines.append_array(ab_lines)

	# Kill units
	for u in units_to_kill:
		log_lines.append("> %s (P%d) was killed" % [u.display_name(), u.owner_index + 1])
		gs.board.remove_unit_from_battlefield(u)
		var owner_ps: PlayerState = gs.players[u.owner_index]
		owner_ps.move_to_trash(u)

	return log_lines


static func _recall_unattached_gear(gs: GameState, log_lines: Array) -> void:
	for bf in gs.board.battlefields:
		for pi in range(bf.units.size()):
			var units_copy = Array(bf.units[pi])
			for u in units_copy:
				for gear in Array(u.attached_gear):
					# Gear stays attached as long as unit is on the battlefield
					pass
	# Unattached gear at battlefields (not attached to any unit)
	for pi in range(gs.players.size()):
		var ps: PlayerState = gs.players[pi]
		for gear in Array(ps.base_permanents):
			if gear.definition.card_type == "gear" and gear.attached_to == null:
				if gear.is_at_battlefield():
					# Recall to base
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


static func _prompt_staged(gs: GameState) -> Array:
	var log_lines: Array[String] = []
	# Auto-start the first staged combat or showdown
	if not gs.board.staged_combats.is_empty():
		var bf_idx = gs.board.staged_combats[0]
		gs.board.staged_combats.erase(bf_idx)
		gs.board.staged_showdowns.erase(bf_idx)
		gs.board.battlefields[bf_idx].is_contested = false
		gs.combat_bf_index = bf_idx
		gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
		# Focus goes to the player who moved in (contested applicant)
		# We track attacker index set during movement
		gs.focus_player_index = gs.attacker_player_index if gs.attacker_player_index >= 0 else gs.turn_player_index
		log_lines.append("> Combat begins at %s — P%d has Focus" % [
			gs.board.battlefields[bf_idx].display_name, gs.focus_player_index + 1
		])
		log_lines.append("[PROMPT] P%d: Play an Action/Reaction card or 'pass' to continue to combat damage." % (gs.focus_player_index + 1))
	elif not gs.board.staged_showdowns.is_empty():
		var bf_idx = gs.board.staged_showdowns[0]
		gs.board.staged_showdowns.erase(bf_idx)
		gs.board.battlefields[bf_idx].is_contested = false
		gs.board.active_showdown_bf = bf_idx
		gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
		gs.focus_player_index = gs.turn_player_index
		log_lines.append("> Non-combat Showdown at %s — P%d has Focus" % [
			gs.board.battlefields[bf_idx].display_name, gs.focus_player_index + 1
		])
		log_lines.append("[PROMPT] P%d: Play an Action/Reaction card or 'pass'." % (gs.focus_player_index + 1))
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
