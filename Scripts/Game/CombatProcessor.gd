class_name CombatProcessor

static func begin_combat(bf_index: int, attacker_player: int, gs: GameState, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	gs.combat_bf_index = bf_index
	gs.attacker_player_index = attacker_player
	var defender_player = 1 - attacker_player

	var bf = gs.board.battlefields[bf_index]
	bf.is_contested = false

	for u in bf.units[attacker_player]:
		u.is_attacker = true
		u.is_defender = false
	for u in bf.units[defender_player]:
		u.is_defender = true
		u.is_attacker = false

	gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
	gs.focus_player_index = attacker_player
	gs.passes_in_sequence = 0

	if controller != null:
		for line in controller.trigger_dispatcher.emit("on_defend", {
			"battlefield_index": bf_index,
			"player_index": defender_player,
			"controller": controller,
		}, gs, controller):
			log_lines.append(line)

	log_lines.append("> Combat begins at %s — P%d attacks, P%d defends" % [
		bf.display_name, attacker_player + 1, defender_player + 1
	])
	log_lines.append("[PROMPT] P%d: play Action/Reaction card or 'pass' to proceed to damage" % (attacker_player + 1))
	return log_lines


static func handle_pass(gs: GameState, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	var passer = gs.focus_player_index
	log_lines.append("> [P%d] Passed Focus" % (passer + 1))
	gs.passes_in_sequence += 1

	if gs.passes_in_sequence >= gs.players.size():
		return proceed_to_damage(gs, controller)
	else:
		gs.focus_player_index = (gs.focus_player_index + 1) % gs.players.size()
		log_lines.append("[PROMPT] P%d: play Action/Reaction card or 'pass'" % (gs.focus_player_index + 1))
	return log_lines


static func proceed_to_damage(gs: GameState, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	var bf_index = gs.combat_bf_index
	var bf = gs.board.battlefields[bf_index]
	var attacker = gs.attacker_player_index
	var defender = 1 - attacker

	var atk_units = Array(bf.units[attacker])
	var def_units = Array(bf.units[defender])

	if atk_units.is_empty() or def_units.is_empty():
		log_lines.append("> No opposing units — combat ends without damage")
		return finalize_combat(gs, log_lines, controller)

	_ensure_combat_designations(gs)
	atk_units = Array(bf.units[attacker])
	def_units = Array(bf.units[defender])

	log_lines.append("> Combat Damage Step at %s" % bf.display_name)

	if not gs.auto_combat_damage:
		var atk_might = _sum_might(atk_units, true)
		gs.combat_assignment_active = true
		gs.remaining_attacker_might = atk_might
		gs.damage_assignments.clear()
		log_lines.append("> Attacker must assign %d damage — use: assign <n> to <id>  |  assign done" % atk_might)
		return log_lines

	var atk_might = _sum_might(atk_units, true)
	var def_might = _sum_might(def_units, false)
	log_lines.append(">   Attackers total Might: %d | Defenders total Might: %d" % [atk_might, def_might])

	var atk_assignments = _auto_assign_damage(atk_might, def_units, true)
	var def_assignments = _auto_assign_damage(def_might, atk_units, false)

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

	return finalize_combat(gs, log_lines, controller)


static func finalize_assignments(gs: GameState, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	var bf = gs.board.battlefields[gs.combat_bf_index]
	var attacker = gs.attacker_player_index
	var defender = 1 - attacker
	var def_units = bf.units[defender]

	for inst_id in gs.damage_assignments:
		var unit = _find_unit(def_units, inst_id)
		if unit:
			unit.add_damage(gs.damage_assignments[inst_id])
			log_lines.append(">   Dealt %d damage to %s" % [gs.damage_assignments[inst_id], unit.display_name()])

	gs.combat_assignment_active = false
	gs.damage_assignments.clear()
	gs.remaining_attacker_might = 0

	# Defender auto-assigns back
	var atk_units = bf.units[attacker]
	var def_might = _sum_might(def_units, false)
	var atk_might = _sum_might(atk_units, true)
	var def_assignments = _auto_assign_damage(def_might, atk_units, false)
	for inst_id in def_assignments:
		var unit = _find_unit(atk_units, inst_id)
		if unit:
			unit.add_damage(def_assignments[inst_id])
			log_lines.append(">   Dealt %d damage to %s" % [def_assignments[inst_id], unit.display_name()])

	return finalize_combat(gs, log_lines, controller)


static func _ensure_combat_designations(gs: GameState) -> void:
	if gs.combat_bf_index < 0 or gs.attacker_player_index < 0:
		return
	var bf = gs.board.battlefields[gs.combat_bf_index]
	var attacker = gs.attacker_player_index
	var defender = 1 - attacker
	for u in bf.units[attacker]:
		u.is_attacker = true
		u.is_defender = false
	for u in bf.units[defender]:
		u.is_defender = true
		u.is_attacker = false


static func _sum_might(units: Array, as_attacker: bool) -> int:
	var total = 0
	for u in units:
		if u.is_stunned:
			continue
		total += u.get_current_might()
	return total


static func _auto_assign_damage(might: int, targets: Array, _attacker_assigning: bool) -> Dictionary:
	var assignments: Dictionary = {}
	var remaining = might
	if remaining <= 0:
		return assignments

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


static func finalize_combat(gs: GameState, log_lines: Array, controller: GameController = null) -> Array:
	var bf_index = gs.combat_bf_index
	var bf = gs.board.battlefields[bf_index]
	var attacker = gs.attacker_player_index
	var defender = 1 - attacker

	var resolver: AbilityResolver = null
	if controller != null:
		resolver = controller.ability_resolver
	log_lines.append_array(CleanupProcessor.process_deaths(gs, resolver, controller))

	for player_units in bf.units:
		for u in player_units:
			u.heal_all()

	var atk_has = not bf.units[attacker].is_empty()
	var def_has = not bf.units[defender].is_empty()

	if atk_has and not def_has:
		log_lines.append("> Attacker wins combat at %s!" % bf.display_name)
		log_lines.append_array(ShowdownProcessor.establish_control(gs, bf_index, attacker, true, controller))
	elif def_has and not atk_has:
		log_lines.append("> Defender wins combat at %s" % bf.display_name)
		if bf.controller_index < 0:
			log_lines.append_array(ShowdownProcessor.establish_control(gs, bf_index, defender, true, controller))
	else:
		if atk_has:
			log_lines.append("> Combat inconclusive — Attacker units recalled to base")
			for u in Array(bf.units[attacker]):
				gs.board.remove_unit_from_battlefield(u)
				u.location = "base"
				u.is_exhausted = true
				gs.players[attacker].base_permanents.append(u)
		if not def_has and not atk_has:
			bf.controller_index = -1

	for player_units in bf.units:
		for u in player_units:
			u.is_attacker = false
			u.is_defender = false

	gs.combat_bf_index = -1
	gs.attacker_player_index = -1
	gs.combat_assignment_active = false
	gs.current_state = TurnStateMachine.State.NEUTRAL_OPEN
	gs.focus_player_index = -1
	gs.passes_in_sequence = 0
	log_lines.append("> Combat at %s resolved" % bf.display_name)

	if not gs.board.staged_combats.is_empty():
		var next_idx = gs.board.staged_combats[0]
		gs.board.staged_combats.erase(next_idx)
		return log_lines + begin_combat(next_idx, gs.turn_player_index, gs, controller)

	return log_lines
