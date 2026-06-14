class_name TriggerDispatcher

const ConditionEvaluatorScript = preload("res://Scripts/Game/ConditionEvaluator.gd")
const TargetResolverScript = preload("res://Scripts/Game/TargetResolver.gd")
const CostCalculatorScript = preload("res://Scripts/Game/CostCalculator.gd")

var _pending_end_of_turn: Array = []


func emit(event: String, ctx: Dictionary, gs: GameState, controller: GameController = null) -> Array:
	if event == "on_play":
		return _emit_played_card_abilities(ctx, gs, controller, 0)

	var log_lines: Array[String] = []
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
			for ab in u.definition.abilities:
				if ab.get("ability_type", "") != "passive":
					continue
				if ab.get("effect_type", "") != "gain_keywords":
					continue
				if not ConditionEvaluatorScript.evaluate(ab.get("condition", null), u, gs, {}):
					continue
				for kw in ab.get("effect_params", {}).get("keywords", []):
					u.passive_keywords.append(kw)


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
		if played is CardInstance:
			for ab in played.definition.abilities:
				results.append({"source": played, "ability": ab})
		return results

	if event == "on_discard":
		var discarded: CardInstance = ctx.get("discarded_card")
		if discarded:
			for ab in discarded.definition.abilities:
				results.append({"source": discarded, "ability": ab})
		return results

	for ps in gs.players:
		if ps.legend and event == "beginning_phase_start":
			for ab in ps.legend.definition.abilities:
				results.append({"source": ps.legend, "ability": ab})

	for i in range(gs.board.battlefields.size()):
		if event in ["on_conquer", "on_defend"] and bf_idx >= 0 and i != bf_idx:
			continue
		var bf = gs.board.battlefields[i]
		if bf.card_def:
			for ab in bf.card_def.abilities:
				results.append({"source": null, "ability": ab, "battlefield_index": i})

	for ps in gs.players:
		for perm in ps.base_permanents:
			for ab in perm.definition.abilities:
				results.append({"source": perm, "ability": ab})
		for u in gs.board.get_all_units_on_board(ps.player_index):
			for ab in u.definition.abilities:
				results.append({"source": u, "ability": ab})

	return results


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
