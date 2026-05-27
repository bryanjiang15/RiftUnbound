class_name LegalMoveEnumerator

# Enumerates all legal command strings for the AI player given the current
# GameState.  Every string returned here should pass GameController.submit_command
# without producing an [ERROR] line.
#
# Used by:
#   - BriefStateSerializer (to populate brief_state.legal_moves)
#   - The heuristic fallback inside AIPlayer when HTTP fails
#   - The Python list_legal_moves skill (via the brief state payload)


static func enumerate(gs: GameState, player_index: int) -> Array:
	var moves: Array = []

	# ── Mulligan ─────────────────────────────────────────────────────────────
	if gs.mulligan_phase:
		if gs.mulligan_done[player_index]:
			return []
		moves.append("mulligan keep")
		var ps: PlayerState = gs.players[player_index]
		# Single-card mulligan options
		for c in ps.hand:
			moves.append("mulligan %s" % c.instance_id)
		# Two-card mulligan options
		for i in range(ps.hand.size()):
			for j in range(i + 1, ps.hand.size()):
				moves.append("mulligan %s %s" % [ps.hand[i].instance_id, ps.hand[j].instance_id])
		return moves

	# ── Pending choice ────────────────────────────────────────────────────────
	if not gs.pending_prompt.is_empty():
		if gs.pending_prompt.get("player_index", -1) != player_index:
			return []
		for choice in gs.pending_prompt.get("valid_choices", []):
			moves.append("choose %s" % choice)
		moves.append("choose none")
		return moves

	# ── Combat damage assignment ──────────────────────────────────────────────
	if gs.combat_assignment_active:
		if gs.attacker_player_index != player_index:
			return []
		return _enumerate_combat_assignments(gs)

	# ── Showdown / closed chain ───────────────────────────────────────────────
	if gs.is_showdown_state():
		if gs.focus_player_index != player_index:
			return []
		moves.append("pass")
		_add_reaction_plays(gs, player_index, moves)
		return moves

	if not gs.chain.is_empty():
		moves.append("pass")
		_add_reaction_plays(gs, player_index, moves)
		return moves

	# ── Main phase — neutral open ─────────────────────────────────────────────
	if gs.turn_player_index != player_index:
		return []
	if gs.current_phase != TurnStateMachine.Phase.MAIN:
		return []

	var ps: PlayerState = gs.players[player_index]

	# Play cards from hand (runes auto-pay on play — no manual tap/recycle)
	_add_playable_cards(gs, ps, player_index, moves)

	# Move ready units from base to battlefields
	_add_unit_moves_from_base(gs, ps, player_index, moves)

	# Move ready units between battlefields (Ganking keyword)
	_add_ganking_moves(gs, player_index, moves)

	# Activate activated abilities on board permanents
	_add_activated_abilities(gs, ps, player_index, moves)

	# Play champion from champion zone
	if ps.champion_zone != null and not ps.champion_zone.is_exhausted:
		var champ: CardInstance = ps.champion_zone
		var cost = CostCalculator.compute_play_cost(champ, player_index, gs)
		if CostCalculator.can_afford(player_index, cost, gs):
			moves.append("play %s from champion" % champ.instance_id)

	moves.append("end turn")
	return moves


# ── Helpers ───────────────────────────────────────────────────────────────────

static func _add_playable_cards(gs: GameState, ps: PlayerState, player_index: int, moves: Array) -> void:
	var bf_ids: Array = []
	for bf in gs.board.battlefields:
		bf_ids.append(bf.battlefield_id)

	for card in ps.hand:
		if card.definition.card_type == "rune":
			continue
		if card.definition.is_reaction:
			continue  # reactions are played via react/chain, not play

		var cost = CostCalculator.compute_play_cost(card, player_index, gs)
		if not CostCalculator.can_afford(player_index, cost, gs):
			continue

		if card.definition.card_type == "unit":
			# Units must be played to base (Ambush keyword not yet implemented).
			moves.append("play %s" % card.instance_id)
			# Accelerate option (still goes to base, just enters Ready)
			if card.has_keyword("accelerate"):
				var accel_cost = CostCalculator.compute_play_cost(card, player_index, gs, true)
				if CostCalculator.can_afford(player_index, accel_cost, gs):
					moves.append("play %s accelerate" % card.instance_id)
		elif card.definition.card_type == "gear":
			moves.append("play %s" % card.instance_id)
		elif card.definition.card_type == "spell":
			if card.definition.is_action:
				# action spells can be played in main phase
				moves.append("play %s" % card.instance_id)
			else:
				moves.append("play %s" % card.instance_id)


static func _add_unit_moves_from_base(gs: GameState, ps: PlayerState, player_index: int, moves: Array) -> void:
	var ready_units = []
	for u in ps.get_units_at_base():
		if not u.is_exhausted:
			ready_units.append(u)
	if ready_units.is_empty():
		return

	for bf in gs.board.battlefields:
		for unit in ready_units:
			moves.append("move %s to %s" % [unit.instance_id, bf.battlefield_id])

		# Multiple simultaneous moves to same destination
		if ready_units.size() >= 2:
			for i in range(ready_units.size()):
				for j in range(i + 1, ready_units.size()):
					moves.append("move %s %s to %s" % [
						ready_units[i].instance_id,
						ready_units[j].instance_id,
						bf.battlefield_id
					])


static func _add_ganking_moves(gs: GameState, player_index: int, moves: Array) -> void:
	var bf_ids: Array = []
	for bf in gs.board.battlefields:
		bf_ids.append(bf.battlefield_id)

	for bf in gs.board.battlefields:
		for unit in bf.units[player_index]:
			if unit.has_keyword("ganking") and not unit.is_exhausted:
				for target_bf_id in bf_ids:
					if target_bf_id != bf.battlefield_id:
						moves.append("move %s to %s" % [unit.instance_id, target_bf_id])


static func _add_activated_abilities(gs: GameState, ps: PlayerState, player_index: int, moves: Array) -> void:
	var board_permanents: Array = []
	board_permanents.append_array(ps.base_permanents)
	for bf in gs.board.battlefields:
		board_permanents.append_array(bf.units[player_index])

	for perm in board_permanents:
		for ab in perm.definition.abilities:
			if ab.get("ability_type", "") != "activated":
				continue
			var cost = CostCalculator.compute_ability_cost(ab, perm, null, gs)
			if not CostCalculator.can_afford(player_index, cost, gs):
				continue
			if cost.get("exhaust", false) and perm.is_exhausted:
				continue
			# Without target
			moves.append("use %s" % perm.instance_id)
			# With targets if ability needs one
			if ab.get("effect_params", {}).get("target", "") != "":
				var all_units = gs.get_all_units_visible_to(player_index)
				for t in all_units:
					moves.append("use %s target %s" % [perm.instance_id, t.instance_id])


static func _add_reaction_plays(gs: GameState, player_index: int, moves: Array) -> void:
	var ps: PlayerState = gs.players[player_index]
	for card in ps.hand:
		if not card.definition.is_reaction:
			continue
		var cost = CostCalculator.compute_play_cost(card, player_index, gs)
		if CostCalculator.can_afford(player_index, cost, gs):
			moves.append("react %s" % card.instance_id)


static func _enumerate_combat_assignments(gs: GameState) -> Array:
	var moves: Array = []
	if gs.combat_bf_index < 0 or gs.combat_bf_index >= gs.board.battlefields.size():
		return ["assign done"]

	var bf = gs.board.battlefields[gs.combat_bf_index]
	var defender_pi = 1 - gs.attacker_player_index
	var defender_units = bf.units[defender_pi]

	# Each defender unit can receive between 1 and remaining_attacker_might damage
	var remaining = gs.remaining_attacker_might
	if remaining <= 0:
		moves.append("assign done")
		return moves

	for unit in defender_units:
		if unit.instance_id in gs.damage_assignments:
			continue  # already assigned
		for amount in range(1, remaining + 1):
			moves.append("assign %d to %s" % [amount, unit.instance_id])

	moves.append("assign done")
	return moves
