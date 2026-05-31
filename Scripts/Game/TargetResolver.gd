class_name TargetResolver

const ConditionEvaluatorScript = preload("res://Scripts/Game/ConditionEvaluator.gd")

static func get_valid_targets(filter: String, source: CardInstance, gs: GameState, ctx: Dictionary = {}) -> Array:
	var results: Array = []
	var owner = source.owner_index if source else ctx.get("player_index", 0)
	match filter:
		"self":
			if source:
				results.append(source)
		"friendly_unit":
			results.append_array(_friendly_units(owner, gs))
		"enemy_unit":
			results.append_array(_enemy_units(owner, gs))
		"unit_at_battlefield":
			results.append_array(_all_board_units(gs))
		"friendly_unit_at_battlefield":
			results.append_array(_friendly_units_on_bf(owner, gs))
		"enemy_unit_at_battlefield":
			results.append_array(_enemy_units_on_bf(owner, gs))
		"friendly_unit_here":
			var bf_idx = ctx.get("battlefield_index", -1)
			if bf_idx >= 0:
				for u in gs.board.battlefields[bf_idx].units[owner]:
					results.append(u)
		"unit_or_gear_at_battlefield":
			results.append_array(_all_board_units(gs))
			for ps in gs.players:
				for g in ps.get_unattached_gear_at_base():
					results.append(g)
		"any_unit":
			results.append_array(_all_board_units(gs))
		"unit":
			for ps in gs.players:
				for c in ps.trash:
					if c.definition.card_type == "unit":
						results.append(c)
		_:
			results.append_array(_all_board_units(gs))
	return results


static func filter_with_params(filter: String, params: Dictionary, source: CardInstance, gs: GameState, ctx: Dictionary = {}) -> Array:
	var raw = get_valid_targets(filter, source, gs, ctx)
	var out: Array = []
	for t in raw:
		if ConditionEvaluatorScript.evaluate_target_filter(params, t, source, gs):
			out.append(t)
	return out


static func _friendly_units(owner: int, gs: GameState) -> Array:
	var r: Array = []
	r.append_array(gs.players[owner].get_units_at_base())
	r.append_array(gs.board.get_all_units_on_board(owner))
	return r


static func _enemy_units(owner: int, gs: GameState) -> Array:
	return _friendly_units(1 - owner, gs)


static func _all_board_units(gs: GameState) -> Array:
	var r: Array = []
	for bf in gs.board.battlefields:
		for player_units in bf.units:
			r.append_array(player_units)
	return r


static func _friendly_units_on_bf(owner: int, gs: GameState) -> Array:
	var r: Array = []
	for bf in gs.board.battlefields:
		r.append_array(bf.units[owner])
	return r


static func _enemy_units_on_bf(owner: int, gs: GameState) -> Array:
	return _friendly_units_on_bf(1 - owner, gs)
