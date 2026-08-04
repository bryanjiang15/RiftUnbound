class_name TriggerDispatcher

const ConditionEvaluatorScript = preload("res://Scripts/Game/ConditionEvaluator.gd")
const TargetResolverScript = preload("res://Scripts/Game/TargetResolver.gd")
const CostCalculatorScript = preload("res://Scripts/Game/CostCalculator.gd")

var _pending_end_of_turn: Array = []


func emit(event: String, ctx: Dictionary, gs: GameState, controller: GameController = null) -> Array:
	var log_lines: Array[String] = []
	if event == "on_play":
		log_lines.append_array(_emit_played_card_abilities(ctx, gs, controller, 0))
		if not gs.pending_prompt.is_empty():
			return log_lines
		ctx = ctx.duplicate()
		ctx["skip_played_card_source"] = true

	var resolver = controller.ability_resolver if controller else AbilityResolver.new()

	for entry in _collect_sources(event, ctx, gs):
		var source: Variant = entry.get("source")
		var ab: Dictionary = entry.get("ability", {})
		if str(ab.get("timing", "")) != event:
			continue
		if ab.get("effect_type", "") == "cost_reduction":
			continue
		var condition = ab.get("condition", null)
		if not ConditionEvaluatorScript.evaluate(condition, source, gs, ctx):
			continue
		if ab.get("is_optional", false) and controller != null:
			log_lines.append(_prompt_optional(source, ab, ctx, gs))
			return log_lines
		var owner_pi = _owner_index(source, ctx)
		var cost = ab.get("cost", {})
		if not cost.is_empty():
			var computed = CostCalculatorScript.compute_ability_cost(cost, source if source is CardInstance else null, null, gs)
			var discard_n = CostCalculatorScript.discard_count(computed)
			if discard_n > 0 and controller != null:
				log_lines.append_array(controller.begin_discard(owner_pi, discard_n, {
					"kind": "trigger_after_discard_cost",
					"ability": ab,
					"source": source,
					"ctx": ctx,
					"computed": computed,
				}, source if source is CardInstance else null, ab))
				return log_lines
			if controller != null:
				if not controller.try_pay_cost(owner_pi, computed, source if source is CardInstance else null):
					continue
			elif not CostCalculatorScript.can_afford(owner_pi, computed, gs):
				continue
			else:
				CostCalculatorScript.pay_cost(owner_pi, computed, source if source is CardInstance else null, gs)
		var params = ab.get("effect_params", {})
		if params.get("targeting", "") == "choose_one" and controller != null:
			var prompt_line = _prompt_mandatory_target(source, ab, ctx, gs)
			if not prompt_line.is_empty():
				log_lines.append(prompt_line)
				return log_lines
		var target = _resolve_trigger_target(ab, source, ctx, gs)
		var effect_ctx = ctx.duplicate()
		effect_ctx["controller"] = controller
		if ab.get("effect_type", "") == "ready_runes" and ab.get("effect_params", {}).get("timing", "") == "end_of_turn":
			queue_end_of_turn(source, ab, effect_ctx)
			log_lines.append("> Scheduled ready_runes at end of turn")
			continue
		log_lines.append_array(resolver.resolve_ability(ab, source, target, gs, effect_ctx))
		if not gs.pending_prompt.is_empty():
			return log_lines

	if gs.pending_prompt.is_empty():
		emit_passive_auras(gs)
	return log_lines


func emit_passive_auras(gs: GameState) -> void:
	for ps in gs.players:
		var all_units: Array = []
		all_units.append_array(ps.get_units_at_base())
		all_units.append_array(gs.board.get_all_units_on_board(ps.player_index))
		for u in all_units:
			u.passive_keywords.clear()
			u.passive_might_bonus = 0
		# Self passive abilities (keyword grants + conditional Might).
		for u in all_units:
			for ab in u.definition.abilities:
				if ab.get("ability_type", "") != "passive":
					continue
				if not ConditionEvaluatorScript.evaluate(ab.get("condition", null), u, gs, {}):
					continue
				match ab.get("effect_type", ""):
					"gain_keywords":
						for kw in ab.get("effect_params", {}).get("keywords", []):
							u.passive_keywords.append(kw)
					"conditional_might":
						var ep: Dictionary = ab.get("effect_params", {})
						if ep.get("per_card_in_trash", false):
							u.passive_might_bonus += ps.trash.size() * int(ep.get("amount_per_card", 1))
						else:
							u.passive_might_bonus += int(ep.get("amount", 0))
		# Legend auras that buff friendly units (e.g. Master Yi - Wuju Bladesman).
		if ps.legend != null:
			for ab in ps.legend.definition.abilities:
				if ab.get("ability_type", "") != "passive":
					continue
				if ab.get("effect_type", "") != "aura_might":
					continue
				var amount := int(ab.get("effect_params", {}).get("amount", 0))
				var cond = ab.get("condition", null)
				for u in all_units:
					# The aura condition is evaluated per affected unit.
					if ConditionEvaluatorScript.evaluate(cond, u, gs, {}):
						u.passive_might_bonus += amount


func queue_end_of_turn(source: Variant, ability: Dictionary, ctx: Dictionary) -> void:
	_pending_end_of_turn.append({"source": source, "ability": ability, "ctx": ctx})


func process_end_of_turn(gs: GameState, controller: GameController) -> Array:
	var log_lines: Array[String] = []
	for entry in _pending_end_of_turn:
		var source = entry["source"]
		var ab: Dictionary = entry["ability"]
		var ctx: Dictionary = entry["ctx"]
		log_lines.append_array(controller.ability_resolver.resolve_ability(ab, source, null, gs, ctx))
	_pending_end_of_turn.clear()
	return log_lines


func _collect_sources(event: String, ctx: Dictionary, gs: GameState) -> Array:
	var results: Array = []
	var bf_idx = ctx.get("battlefield_index", -1)

	if event == "on_play":
		var played: Variant = ctx.get("source")
		if played is CardInstance and not ctx.get("skip_played_card_source", false):
			for ab in played.definition.abilities:
				results.append({"source": played, "ability": ab})
		if not ctx.get("skip_played_card_source", false):
			return results

	if event == "on_discard":
		var discarded: CardInstance = ctx.get("discarded_card")
		if discarded:
			for ab in discarded.definition.abilities:
				results.append({"source": discarded, "ability": ab})
		return results

	if event == "on_move":
		var moved: Variant = ctx.get("source")
		if moved is CardInstance:
			for ab in moved.definition.abilities:
				results.append({"source": moved, "ability": ab})
		return results

	if event == "beginning_phase_start":
		var active_pi = int(ctx.get("player_index", -1))
		if active_pi >= 0 and active_pi < gs.players.size():
			var ps = gs.players[active_pi]
			if ps.legend:
				for ab in ps.legend.definition.abilities:
					results.append({"source": ps.legend, "ability": ab})

	for i in range(gs.board.battlefields.size()):
		if event in ["on_conquer", "on_defend", "hold"] and bf_idx >= 0 and i != bf_idx:
			continue
		var bf = gs.board.battlefields[i]
		if bf.card_def:
			for ab in bf.card_def.abilities:
				results.append({"source": null, "ability": ab, "battlefield_index": i})

	for ps in gs.players:
		if event == "on_play" and ps.legend != null:
			for ab in ps.legend.definition.abilities:
				if not _is_play_observer_ability(ab):
					continue
				results.append({"source": ps.legend, "ability": ab})
		for perm in ps.base_permanents:
			if ctx.get("skip_played_card_source", false) and perm == ctx.get("source"):
				continue
			for ab in perm.definition.abilities:
				if event == "on_play" and ctx.get("skip_played_card_source", false) and not _is_play_observer_ability(ab):
					continue
				if event == "on_conquer" and not _unit_conquers_here(perm, ctx):
					continue
				results.append({"source": perm, "ability": ab})
		for u in gs.board.get_all_units_on_board(ps.player_index):
			if ctx.get("skip_played_card_source", false) and u == ctx.get("source"):
				continue
			for ab in u.definition.abilities:
				if event == "on_play" and ctx.get("skip_played_card_source", false) and not _is_play_observer_ability(ab):
					continue
				if event == "on_conquer" and not _unit_conquers_here(u, ctx):
					continue
				results.append({"source": u, "ability": ab})

	return results


func _unit_conquers_here(unit: CardInstance, ctx: Dictionary) -> bool:
	# "When I conquer" — only the conquering player's units at that battlefield.
	var bf_idx = int(ctx.get("battlefield_index", -1))
	var player_index = int(ctx.get("player_index", -1))
	if unit.owner_index != player_index:
		return false
	if not unit.is_at_battlefield():
		return false
	return unit.battlefield_index == bf_idx


func _is_play_observer_ability(ab: Dictionary) -> bool:
	if str(ab.get("timing", "")) != "on_play":
		return false
	var cond = ab.get("condition", null)
	if not cond is Dictionary:
		return false
	return cond.get("type", "") in ["played_card_type", "played_card_count_eq"]


func _owner_index(source: Variant, ctx: Dictionary) -> int:
	if source is CardInstance:
		return source.owner_index
	return int(ctx.get("player_index", 0))


func _resolve_trigger_target(ab: Dictionary, source: Variant, ctx: Dictionary, gs: GameState) -> CardInstance:
	if ctx.has("target") and ctx["target"] is CardInstance:
		return ctx["target"]
	var params = ab.get("effect_params", {})
	var filter: String = params.get("target", "")
	if filter.is_empty():
		return null
	var tctx = ctx.duplicate()
	if source is CardInstance:
		tctx["player_index"] = source.owner_index
	var targets = TargetResolverScript.filter_with_params(filter, params, source if source is CardInstance else null, gs, tctx)
	targets = TargetResolverScript.restrict_to_hidden_battlefield(targets, int(ctx.get("hidden_bf_idx", -1)))
	return targets[0] if not targets.is_empty() else null


func _emit_played_card_abilities(ctx: Dictionary, gs: GameState, controller: GameController, start_index: int) -> Array:
	var log_lines: Array[String] = []
	var source: Variant = ctx.get("source")
	if not source is CardInstance:
		return log_lines
	var resolver = controller.ability_resolver if controller else AbilityResolver.new()
	var abilities: Array = source.definition.abilities
	for i in range(start_index, abilities.size()):
		var ab: Dictionary = abilities[i]
		if str(ab.get("timing", "")) != "on_play":
			continue
		if ab.get("effect_type", "") == "cost_reduction":
			continue
		if ab.get("effect_type", "") == "enter_ready" and (
				ctx.get("use_accelerate", false) or ctx.get("declined_accelerate", false)
		):
			continue
		var condition = ab.get("condition", null)
		if not ConditionEvaluatorScript.evaluate(condition, source, gs, ctx):
			continue
		if ab.get("is_optional", false) and controller != null:
			log_lines.append(_prompt_optional(source, ab, ctx, gs, i + 1))
			return log_lines
		var owner_pi = _owner_index(source, ctx)
		var cost = ab.get("cost", {})
		if not cost.is_empty():
			var computed = CostCalculatorScript.compute_ability_cost(cost, source, null, gs)
			var discard_n = CostCalculatorScript.discard_count(computed)
			if discard_n > 0 and controller != null:
				log_lines.append_array(controller.begin_discard(owner_pi, discard_n, {
					"kind": "trigger_after_discard_cost",
					"ability": ab,
					"source": source,
					"ctx": ctx,
					"computed": computed,
				}, source, ab))
				return log_lines
			if controller != null:
				if not controller.try_pay_cost(owner_pi, computed, source):
					continue
			elif not CostCalculatorScript.can_afford(owner_pi, computed, gs):
				continue
			else:
				CostCalculatorScript.pay_cost(owner_pi, computed, source, gs)
		var params = ab.get("effect_params", {})
		if params.get("targeting", "") == "choose_one" and controller != null:
			var prompt_line = _prompt_mandatory_target(source, ab, ctx, gs, i + 1)
			if not prompt_line.is_empty():
				log_lines.append(prompt_line)
				return log_lines
		var target = _resolve_trigger_target(ab, source, ctx, gs)
		var effect_ctx = ctx.duplicate()
		effect_ctx["controller"] = controller
		log_lines.append_array(resolver.resolve_ability(ab, source, target, gs, effect_ctx))
		if not gs.pending_prompt.is_empty():
			return log_lines

	if gs.pending_prompt.is_empty():
		emit_passive_auras(gs)
	return log_lines


func resume_on_play(ctx: Dictionary, gs: GameState, controller: GameController, next_index: int) -> Array:
	return _emit_played_card_abilities(ctx, gs, controller, next_index)


func _prompt_optional(source: Variant, ab: Dictionary, ctx: Dictionary, gs: GameState, on_play_resume_index: int = -1) -> String:
	var pi = _owner_index(source, ctx)
	var card_name := ""
	if source is CardInstance:
		card_name = source.display_name()
	var prompt_text := "[PROMPT] Optional ability"
	if card_name != "":
		prompt_text += " (%s)" % card_name
	prompt_text += " — choose yes or no (use: choose yes or choose no)"
	gs.pending_prompt = {
		"player_index": pi,
		"type": "choose_optional",
		"ability": ab,
		"source": source,
		"ctx": ctx,
		"valid_choices": ["yes", "no"],
		"prompt": prompt_text,
		"discard_resume": ctx.get("discard_resume", {}),
	}
	if on_play_resume_index >= 0:
		gs.pending_prompt["resume_on_play"] = {
			"ctx": ctx,
			"next_index": on_play_resume_index,
		}
	return gs.pending_prompt["prompt"]


func _prompt_mandatory_target(source: Variant, ab: Dictionary, ctx: Dictionary, gs: GameState, on_play_resume_index: int = -1) -> String:
	var params: Dictionary = ab.get("effect_params", {})
	var filter: String = params.get("target", "")
	if filter.is_empty():
		return ""
	var tctx = ctx.duplicate()
	if source is CardInstance:
		tctx["player_index"] = source.owner_index
	var targets = TargetResolverScript.filter_with_params(
		filter, params, source if source is CardInstance else null, gs, tctx
	)
	targets = TargetResolverScript.restrict_to_hidden_battlefield(targets, int(ctx.get("hidden_bf_idx", -1)))
	if targets.size() <= 1:
		return ""
	var ids: Array[String] = []
	for t in targets:
		if t is CardInstance:
			ids.append(t.instance_id)
	var pi = _owner_index(source, ctx)
	gs.pending_prompt = {
		"player_index": pi,
		"type": "choose_target",
		"valid_choices": targets,
		"trigger_target_resume": {
			"ability": ab,
			"source": source,
			"ctx": ctx,
		},
		"prompt": "[PROMPT] Choose a target — use: choose <%s>" % "|".join(ids),
	}
	if on_play_resume_index >= 0:
		gs.pending_prompt["resume_on_play"] = {
			"ctx": ctx,
			"next_index": on_play_resume_index,
		}
	return gs.pending_prompt["prompt"]
