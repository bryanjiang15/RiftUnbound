class_name BriefStateSerializer

# Serializes the authoritative GameState into the compact BriefState JSON
# understood by the Python AI agent.  Only information the seat at player_index
# is entitled to see is included (no hidden hand contents for the opponent,
# no face-down card identities).
#
# schema_version must match SCHEMA_VERSION in ai_agent/schemas.py.

const SCHEMA_VERSION := "1.0"


static func serialize(gs: GameState, player_index: int) -> Dictionary:
	var ps: PlayerState = gs.players[player_index]
	var opp: PlayerState = gs.players[1 - player_index]

	return {
		"schema_version": SCHEMA_VERSION,
		"game_id": _game_id(gs),
		"turn_number": gs.turn_number,
		"my_player_index": player_index,
		"turn_player_index": gs.turn_player_index,
		"current_phase": gs.get_phase_name(),
		"current_state": gs.get_state_name(),
		"decision_type": _decision_type(gs, player_index),

		# Resources
		"my_score": ps.score,
		"my_energy": ps.rune_pool.energy,
		"my_power": ps.rune_pool.power.duplicate(),
		"my_runes": _serialize_runes(ps),

		# Hand (full for AI seat only)
		"my_hand": _serialize_hand(ps),

		# My board
		"my_base_units": _serialize_units(ps.get_units_at_base()),
		"my_champion": _serialize_champion(ps.champion_zone),

		# Opponent — public info only
		"opponent_score": opp.score,
		"opponent_hand_size": opp.hand.size(),
		"opponent_base_units": _serialize_units(opp.get_units_at_base()),

		# Battlefields
		"battlefields": _serialize_battlefields(gs, player_index),

		# Legal moves enumerated by LegalMoveEnumerator
		"legal_moves": LegalMoveEnumerator.enumerate(gs, player_index),
		"legal_action_categories": _legal_categories(gs, player_index),

		# Pending choice context
		"pending_choice_options": _pending_choices(gs),
		"pending_choice_context": _pending_choice_context(gs),

		# Combat assignment context
		"combat_assignment_active": gs.combat_assignment_active,
		"remaining_attacker_might": gs.remaining_attacker_might,
		"damage_assigned": gs.damage_assignments.duplicate(),

		# Full board description for read skills
		"full_state_text": gs.board_description(),
	}


# ── Decision type ─────────────────────────────────────────────────────────────

static func _decision_type(gs: GameState, player_index: int) -> String:
	if gs.mulligan_phase and not gs.mulligan_done[player_index]:
		return "mulligan"
	if not gs.pending_prompt.is_empty() and \
	   gs.pending_prompt.get("player_index", -1) == player_index:
		return "pending_choice"
	if gs.combat_assignment_active and gs.attacker_player_index == player_index:
		return "combat_assignment"
	if gs.is_showdown_state() and gs.focus_player_index == player_index:
		return "showdown_focus"
	if not gs.chain.is_empty():
		return "chain_reaction"
	return "main_phase"


# ── Runes ─────────────────────────────────────────────────────────────────────

static func _serialize_runes(ps: PlayerState) -> Array:
	var result: Array = []
	for i in range(ps.channeled_runes.size()):
		var rune: CardInstance = ps.channeled_runes[i]
		var domain := ""
		if rune.definition.domain.size() > 0:
			domain = rune.definition.domain[0]
		result.append({
			"rune_index": i,
			"domain": domain,
			"is_exhausted": rune.is_exhausted,
		})
	return result


# ── Hand ──────────────────────────────────────────────────────────────────────

static func _serialize_hand(ps: PlayerState) -> Array:
	var result: Array = []
	for c in ps.hand:
		if c.definition.card_type == "rune":
			continue
		var keywords: Array = []
		for kw in c.definition.keywords:
			keywords.append(kw.get("id", ""))
		var power_cost: Array = []
		for pc in c.definition.power_cost:
			power_cost.append({"domain": pc.get("domain", ""), "amount": pc.get("amount", 1)})
		result.append({
			"instance_id": c.instance_id,
			"name": c.definition.name,
			"card_type": c.definition.card_type,
			"energy_cost": c.definition.energy_cost,
			"power_cost": power_cost,
			"might": c.definition.might if c.definition.card_type == "unit" else null,
			"keywords": keywords,
			"is_reaction": c.definition.is_reaction,
			"is_action": c.definition.is_action,
			"effect_text": c.definition.effect_text,
		})
	return result


# ── Units ─────────────────────────────────────────────────────────────────────

static func _serialize_units(units: Array) -> Array:
	var result: Array = []
	for u in units:
		result.append(_serialize_unit(u))
	return result


static func _serialize_unit(u: CardInstance) -> Dictionary:
	var keywords: Array = []
	for kw in u.definition.keywords:
		keywords.append(kw.get("id", ""))
	return {
		"instance_id": u.instance_id,
		"name": u.definition.name,
		"current_might": u.get_current_might(),
		"base_might": u.get_base_might(),
		"location": u.location,
		"is_exhausted": u.is_exhausted,
		"is_stunned": u.is_stunned,
		"damage": u.damage,
		"buff_counters": u.buff_counters,
		"keywords": keywords,
		"is_attacker": u.is_attacker,
		"is_defender": u.is_defender,
		"effect_text": u.definition.effect_text,
	}


static func _serialize_champion(champion: CardInstance) -> Variant:
	if champion == null:
		return null
	return _serialize_unit(champion)


# ── Battlefields ──────────────────────────────────────────────────────────────

static func _serialize_battlefields(gs: GameState, player_index: int) -> Array:
	var result: Array = []
	for bf in gs.board.battlefields:
		var bf_effect := ""
		if bf.card_def:
			bf_effect = bf.card_def.effect_text
		result.append({
			"battlefield_id": bf.battlefield_id,
			"display_name": bf.display_name,
			"controller_index": bf.controller_index,
			"my_units": _serialize_units(bf.units[player_index]),
			"opponent_units": _serialize_units(bf.units[1 - player_index]),
			"is_contested": bf.is_contested,
			"has_facedown": bf.facedown_card != null,
			"effect_text": bf_effect,
		})
	return result


# ── Legal action categories ───────────────────────────────────────────────────

static func _legal_categories(gs: GameState, player_index: int) -> Array:
	var cats: Array = []
	if gs.mulligan_phase and not gs.mulligan_done[player_index]:
		cats.append("mulligan")
		return cats
	if not gs.pending_prompt.is_empty():
		cats.append("choose")
		return cats
	if gs.combat_assignment_active:
		cats.append("assign_damage")
		cats.append("assign_done")
		return cats
	if gs.is_showdown_state():
		cats.append("pass")
		var ps: PlayerState = gs.players[player_index]
		for c in ps.hand:
			if c.definition.is_reaction:
				cats.append("react")
				break
		return cats
	if not gs.chain.is_empty():
		cats.append("pass")
		return cats
	# Main phase
	cats.append("tap_rune")
	cats.append("recycle_rune")
	cats.append("play_card")
	cats.append("move_unit")
	cats.append("end_turn")
	return cats


# ── Pending choices ───────────────────────────────────────────────────────────

static func _pending_choices(gs: GameState) -> Array:
	if gs.pending_prompt.is_empty():
		return []
	var choices = gs.pending_prompt.get("valid_choices", [])
	var result: Array = []
	for c in choices:
		if c is CardInstance:
			result.append(c.instance_id)
		else:
			result.append(str(c))
	return result


static func _pending_choice_context(gs: GameState) -> Dictionary:
	if gs.pending_prompt.is_empty():
		return {}

	var result: Dictionary = {
		"prompt_text": gs.pending_prompt.get("prompt", ""),
		"prompt_type": gs.pending_prompt.get("type", ""),
	}

	# Source card (e.g. the unit whose triggered ability fired)
	var source = gs.pending_prompt.get("source", null)
	if source != null and source is CardInstance:
		result["source_card_name"] = source.definition.name
		result["source_card_id"] = source.instance_id
		if source.definition.effect_text:
			result["source_effect_text"] = source.definition.effect_text

	# Ability description for triggered / optional ability prompts
	var ab: Dictionary = gs.pending_prompt.get("ability", {})
	if not ab.is_empty():
		var parts: Array = []
		var timing: String = ab.get("timing", "")
		if timing != "":
			parts.append("trigger: %s" % timing)
		var effect_type: String = ab.get("effect_type", "")
		if effect_type != "":
			parts.append("effect: %s" % effect_type)
		var cost: Dictionary = ab.get("cost", {})
		if not cost.is_empty():
			parts.append("cost: %s" % CostCalculator.cost_to_string(cost))
		if not parts.is_empty():
			result["ability_description"] = "; ".join(parts)

	if gs.pending_prompt.get("type", "") == "choose_discard":
		result["remaining_discards"] = gs.pending_prompt.get("remaining", 1)
		result["mandatory"] = gs.pending_prompt.get("mandatory", true)

	return result


# ── Game ID ───────────────────────────────────────────────────────────────────

static func _game_id(gs: GameState) -> String:
	# Use turn_number + player names as a stable game identifier within session.
	# A real game ID would be set once at game start; this is a session proxy.
	if gs.players.size() >= 2:
		return "%s-vs-%s" % [gs.players[0].player_name, gs.players[1].player_name]
	return "game"
