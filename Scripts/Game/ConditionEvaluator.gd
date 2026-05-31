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
			return target.get_base_might() <= int(condition.get("value", 0))
		_:
			return true


static func evaluate_target_filter(params: Dictionary, target: CardInstance, source: CardInstance, gs: GameState) -> bool:
	if target == null:
		return false
	var cond = params.get("condition", null)
	if cond != null and not evaluate(cond, source, gs, {"target": target}):
		return false
	return true
