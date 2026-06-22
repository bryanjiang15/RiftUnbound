class_name ConditionEvaluator

static func evaluate(condition: Variant, source: CardInstance, gs: GameState, ctx: Dictionary = {}) -> bool:
	if condition == null:
		return true
	if not condition is Dictionary:
		return true
	var ctype: String = condition.get("type", "")
	match ctype:
		"":
			return true
		"legion":
			var pi = source.owner_index if source else ctx.get("player_index", 0)
			return gs.players[pi].cards_played_this_turn > 0
		"hand_size_lte":
			var pi = source.owner_index if source else ctx.get("player_index", 0)
			return gs.players[pi].hand.size() <= int(condition.get("value", 0))
		"discarded_card_this_turn":
			var pi = source.owner_index if source else ctx.get("player_index", 0)
			return gs.players[pi].cards_discarded_count > 0
		"might_lte":
			var target: CardInstance = ctx.get("target")
			if target == null:
				return false
			return target.get_current_might() <= int(condition.get("value", 0))
		"rune_count_gte":
			var pi = source.owner_index if source else ctx.get("player_index", 0)
			return gs.players[pi].channeled_runes.size() >= int(condition.get("value", 0))
		"while_combat_alone":
			# Unit is attacking or defending and is the only friendly unit at its
			# battlefield (i.e. fighting "alone").
			return _is_combat_alone(source, gs)
		"while_defending_alone":
			# Unit is a defender and the only friendly unit at its battlefield.
			return source != null and source.is_defender and _is_combat_alone(source, gs)
		_:
			return true


static func _is_combat_alone(unit: CardInstance, gs: GameState) -> bool:
	if unit == null:
		return false
	if not (unit.is_attacker or unit.is_defender):
		return false
	if not unit.is_at_battlefield():
		return false
	# Only the unit in the *active* combat counts as "attacking/defending alone".
	# Cleanup designates attacker/defender on every contested battlefield while a
	# combat is in progress, so gating on combat_bf_index avoids granting the
	# bonus to units sitting at a different contested battlefield.
	if gs.combat_bf_index < 0 or unit.battlefield_index != gs.combat_bf_index:
		return false
	var bf = gs.board.battlefields[unit.battlefield_index]
	return bf.units[unit.owner_index].size() == 1


static func evaluate_target_filter(params: Dictionary, target: CardInstance, source: CardInstance, gs: GameState) -> bool:
	if target == null:
		return false
	var cond = params.get("condition", null)
	if cond != null and not evaluate(cond, source, gs, {"target": target}):
		return false
	return true
