class_name CombatProcessor

# Combat flow per §12 of implementation rules.

static func begin_combat(bf_index: int, attacker_player: int, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	gs.combat_bf_index = bf_index
	gs.attacker_player_index = attacker_player
	var defender_player = 1 - attacker_player

	var bf = gs.board.battlefields[bf_index]
	bf.is_contested = false

	# Assign attacker/defender designations
	for u in bf.units[attacker_player]:
		u.is_attacker = true
		u.is_defender = false
	for u in bf.units[defender_player]:
		u.is_defender = true
		u.is_attacker = false

	gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
	gs.focus_player_index = attacker_player
	gs.passes_in_sequence = 0

	log_lines.append("> Combat begins at %s — P%d attacks, P%d defends" % [
		bf.display_name, attacker_player + 1, defender_player + 1
	])
	log_lines.append("[PROMPT] P%d: play Action/Reaction card or 'pass' to proceed to damage" % (attacker_player + 1))
	return log_lines


static func handle_pass(gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var passer = gs.focus_player_index
	log_lines.append("> [P%d] Passed Focus" % (passer + 1))
	gs.passes_in_sequence += 1

	if gs.passes_in_sequence >= gs.players.size():
		# All passed → proceed to combat damage
		return proceed_to_damage(gs)
	else:
		gs.focus_player_index = (gs.focus_player_index + 1) % gs.players.size()
		log_lines.append("[PROMPT] P%d: play Action/Reaction card or 'pass'" % (gs.focus_player_index + 1))
	return log_lines


static func proceed_to_damage(gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var bf_index = gs.combat_bf_index
	var bf = gs.board.battlefields[bf_index]
	var attacker = gs.attacker_player_index
	var defender = 1 - attacker

	# Check if both sides still have units
	var atk_units = Array(bf.units[attacker])
	var def_units = Array(bf.units[defender])

	if atk_units.is_empty() or def_units.is_empty():
		log_lines.append("> No opposing units — combat ends without damage")
		return finalize_combat(gs, log_lines)

	log_lines.append("> Combat Damage Step at %s" % bf.display_name)

	# Compute total might for each side
	var atk_might = _sum_might(atk_units, true)
	var def_might = _sum_might(def_units, false)

	log_lines.append(">   Attackers total Might: %d | Defenders total Might: %d" % [atk_might, def_might])

	# Auto-assign attacker damage
	var atk_assignments = _auto_assign_damage(atk_might, def_units, true)
	# Auto-assign defender damage
	var def_assignments = _auto_assign_damage(def_might, atk_units, false)

	# Apply damage simultaneously
	for inst_id in atk_assignments:
		var unit = _find_unit(def_units, inst_id)
		if unit:
			var dmg = atk_assignments[inst_id]
			unit.add_damage(dmg)
			log_lines.append(">   Dealt %d damage to %s" % [dmg, unit.display_name()])

	for inst_id in def_assignments:
		var unit = _find_unit(atk_units, inst_id)
		if unit:
			var dmg = def_assignments[inst_id]
			unit.add_damage(dmg)
			log_lines.append(">   Dealt %d damage to %s" % [dmg, unit.display_name()])

	return finalize_combat(gs, log_lines)


static func _sum_might(units: Array, as_attacker: bool) -> int:
	var total = 0
	for u in units:
		if u.is_stunned:
			continue
		total += u.get_current_might() if as_attacker else u.get_current_might()
	return total


static func _auto_assign_damage(might: int, targets: Array, _attacker_assigning: bool) -> Dictionary:
	# Assign lethal damage to Tank units first, then others
	var assignments: Dictionary = {}
	var remaining = might
	if remaining <= 0:
		return assignments

	# Sort: Tank units first
	var sorted_targets: Array = []
	for t in targets:
		if t.has_keyword("tank"):
			sorted_targets.push_front(t)
		else:
			sorted_targets.append(t)

	for target in sorted_targets:
		if remaining <= 0:
			break
		var lethal = target.get_base_might() - target.damage
		var to_deal = mini(remaining, maxi(lethal, 1))
		assignments[target.instance_id] = to_deal
		remaining -= to_deal

	return assignments


static func _find_unit(units: Array, inst_id: String) -> CardInstance:
	for u in units:
		if u.instance_id == inst_id:
			return u
	return null


static func finalize_combat(gs: GameState, log_lines: Array) -> Array:
	var bf_index = gs.combat_bf_index
	var bf = gs.board.battlefields[bf_index]
	var attacker = gs.attacker_player_index
	var defender = 1 - attacker

	# Heal all units post-combat
	for player_units in bf.units:
		for u in player_units:
			u.heal_all()

	var atk_has = not bf.units[attacker].is_empty()
	var def_has = not bf.units[defender].is_empty()

	if atk_has and not def_has:
		# Attacker wins
		log_lines.append("> Attacker wins combat at %s!" % bf.display_name)
		bf.controller_index = attacker
		var ps: PlayerState = gs.players[attacker]
		if not bf_index in ps.battlefields_scored_this_turn:
			ps.battlefields_scored_this_turn.append(bf_index)
			ps.score += 1
			log_lines.append("> P%d scored 1 point (Conquer). Score: P1=%d, P2=%d" % [
				attacker + 1, gs.players[0].score, gs.players[1].score
			])
	elif def_has and not atk_has:
		# Defender wins — attacker units already killed by cleanup
		log_lines.append("> Defender wins combat at %s" % bf.display_name)
		if bf.controller_index < 0:
			bf.controller_index = defender
	else:
		# Both have units or neither — recall attackers
		if atk_has:
			log_lines.append("> Combat inconclusive — Attacker units recalled to base")
			for u in Array(bf.units[attacker]):
				gs.board.remove_unit_from_battlefield(u)
				u.location = "base"
				u.is_exhausted = true
				gs.players[attacker].base_permanents.append(u)
		if not def_has and not atk_has:
			bf.controller_index = -1

	# Clear designations
	for player_units in bf.units:
		for u in player_units:
			u.is_attacker = false
			u.is_defender = false

	# Reset combat state
	var prev_bf = gs.combat_bf_index
	gs.combat_bf_index = -1
	gs.attacker_player_index = -1
	gs.current_state = TurnStateMachine.State.NEUTRAL_OPEN
	gs.focus_player_index = -1
	gs.passes_in_sequence = 0
	log_lines.append("> Combat at %s resolved" % bf.display_name)

	# Check for more staged combats
	if not gs.board.staged_combats.is_empty():
		var next_idx = gs.board.staged_combats[0]
		gs.board.staged_combats.erase(next_idx)
		return log_lines + begin_combat(next_idx, gs.turn_player_index, gs)

	return log_lines
