class_name CostCalculator

const ConditionEvaluatorScript = preload("res://Scripts/Game/ConditionEvaluator.gd")

static func compute_play_cost(
	card: CardInstance,
	player_index: int,
	gs: GameState,
	use_accelerate: bool = false,
	optional_discard_discount: bool = false
) -> Dictionary:
	var energy = card.definition.energy_cost
	var power = _copy_power_cost(card.definition.power_cost)
	var ps: PlayerState = gs.players[player_index]

	# Passive / triggered cost reductions on the card being played
	for ab in card.definition.abilities:
		if ab.get("effect_type", "") != "cost_reduction":
			continue
		if ab.get("timing", "") == "on_play" and ab.get("is_optional", false) and not optional_discard_discount:
			continue
		if ab.has("condition") and ab.get("condition") != null:
			if not ConditionEvaluatorScript.evaluate(ab.get("condition"), card, gs, {"player_index": player_index}):
				continue
		var ep = ab.get("effect_params", {})
		if ep.get("scope", "self") in ["self", ""]:
			if ep.get("per_card_in_trash", false):
				energy = maxi(0, energy - ps.trash.size() * int(ep.get("reduction_per_card", 1)))
			else:
				energy = maxi(0, energy - int(ep.get("amount", 0)))

	# Legion via ability condition
	for ab in card.definition.abilities:
		var cond = ab.get("condition", {})
		if cond is Dictionary and cond.get("type", "") == "legion":
			if ps.cards_played_this_turn > 0:
				var ep = ab.get("effect_params", {})
				energy = maxi(0, energy - int(ep.get("amount", 2)))

	if use_accelerate and card.has_keyword("accelerate"):
		energy += 1
		if not card.definition.domain.is_empty():
			_add_power_cost(power, card.definition.domain[0], 1)

	energy = maxi(0, energy)
	return {"energy": energy, "power": power, "accelerate": use_accelerate}


static func compute_ability_cost(
	ability_or_cost: Variant,
	source: CardInstance,
	target: CardInstance,
	gs: GameState
) -> Dictionary:
	var cost: Dictionary
	if ability_or_cost is Dictionary and ability_or_cost.has("effect_type"):
		cost = ability_or_cost.get("cost", {})
	elif ability_or_cost is Dictionary:
		cost = ability_or_cost
	else:
		cost = {}

	var energy = cost.get("energy", 0)
	var power = _copy_power_cost(cost.get("power", []))

	if target != null and target.has_keyword("deflect"):
		var deflect_val = target.get_keyword_value("deflect")
		if source != null and source.owner_index != target.owner_index:
			if not target.definition.domain.is_empty():
				_add_power_cost(power, target.definition.domain[0], deflect_val)
			else:
				energy += deflect_val

	return {
		"energy": energy,
		"power": power,
		"exhaust": cost.get("exhaust", false),
		"recycle_self": cost.get("recycle_self", false),
		"recycle": cost.get("recycle", 0),
		"discard": cost.get("discard", 0),
	}


static func can_afford(player_index: int, cost: Dictionary, gs: GameState) -> bool:
	var ps: PlayerState = gs.players[player_index]
	if cost.get("discard", 0) > ps.hand.size():
		return false
	if cost.get("recycle", 0) > ps.deck.size():
		return false
	return ps.rune_pool.can_pay(cost.get("energy", 0), cost.get("power", []))


static func can_afford_with_autopay(player_index: int, cost: Dictionary, gs: GameState) -> bool:
	# Fast path: pool already covers the cost with no auto-pay needed.
	if can_afford(player_index, cost, gs):
		return true

	var ps: PlayerState = gs.players[player_index]
	if cost.get("discard", 0) > ps.hand.size():
		return false
	if cost.get("recycle", 0) > ps.deck.size():
		return false

	# Simulate auto-pay without mutating game state.
	# Domain power: auto-pay recycles matching runes (exhausted first, then untapped).
	# Energy: auto-pay taps untapped runes.
	# Count what would be available after auto-pay.

	# Pool values as starting point
	var sim_energy: int = ps.rune_pool.energy
	var sim_power: Dictionary = ps.rune_pool.power.duplicate()

	# Track runes that would be recycled for domain power (they can't also be tapped)
	var recycled_instance_ids: Array = []

	for pc in cost.get("power", []):
		var domain: String = pc.get("domain", "")
		var needed: int = pc.get("amount", 0)
		if domain == "any":
			var total: int = 0
			for v in sim_power.values():
				total += v
			needed = maxi(0, needed - total)
			for _i in range(needed):
				# Prefer exhausted rune of any domain
				var rune = _find_recyclable_rune_any(ps, recycled_instance_ids)
				if rune == null:
					return false
				recycled_instance_ids.append(rune.instance_id)
				for d in rune.definition.domain:
					sim_power[d] = sim_power.get(d, 0) + 1
		else:
			needed = maxi(0, needed - sim_power.get(domain, 0))
			for _i in range(needed):
				var rune = _find_recyclable_rune_domain(ps, domain, recycled_instance_ids)
				if rune == null:
					return false
				recycled_instance_ids.append(rune.instance_id)
				for d in rune.definition.domain:
					sim_power[d] = sim_power.get(d, 0) + 1

	# Energy: tap untapped runes that weren't recycled above
	var energy_need: int = maxi(0, cost.get("energy", 0) - sim_energy)
	var tapped: int = 0
	for rune in ps.channeled_runes:
		if tapped >= energy_need:
			break
		if not rune.is_exhausted and rune.instance_id not in recycled_instance_ids:
			tapped += 1
	if tapped < energy_need:
		return false

	return true


static func _find_recyclable_rune_domain(ps: PlayerState, domain: String, exclude_ids: Array) -> CardInstance:
	# Prefer exhausted runes of the domain (they can't tap for energy anyway)
	for rune in ps.channeled_runes:
		if rune.instance_id in exclude_ids:
			continue
		if rune.is_exhausted and domain in rune.definition.domain:
			return rune
	for rune in ps.channeled_runes:
		if rune.instance_id in exclude_ids:
			continue
		if domain in rune.definition.domain:
			return rune
	return null


static func _find_recyclable_rune_any(ps: PlayerState, exclude_ids: Array) -> CardInstance:
	for rune in ps.channeled_runes:
		if rune.instance_id not in exclude_ids and rune.is_exhausted:
			return rune
	for rune in ps.channeled_runes:
		if rune.instance_id not in exclude_ids:
			return rune
	return null


static func pay_cost(player_index: int, cost: Dictionary, source: CardInstance, gs: GameState) -> void:
	var ps: PlayerState = gs.players[player_index]
	ps.rune_pool.pay(cost.get("energy", 0), cost.get("power", []))
	if cost.get("exhaust", false) and source != null:
		source.exhaust()
	if cost.get("recycle_self", false) and source != null:
		ps.remove_rune(source)
		ps.recycle_to_bottom(source, true)
	var recycle_n = int(cost.get("recycle", 0))
	for _i in range(recycle_n):
		if ps.deck.is_empty():
			break
		var card = ps.deck.pop_back()
		ps.recycle_to_bottom(card, false)
	var discard_n = int(cost.get("discard", 0))
	for _i in range(discard_n):
		if ps.hand.is_empty():
			break
		var card = ps.hand[0]
		ps.move_to_trash(card)
		ps.cards_discarded_count += 1
		ps.discarded_this_turn.append(card)


static func _copy_power_cost(power_cost: Array) -> Array:
	var result = []
	for pc in power_cost:
		result.append({"domain": pc.get("domain", ""), "amount": pc.get("amount", 1)})
	return result


static func _add_power_cost(power_list: Array, domain_name: String, amount: int) -> void:
	for pc in power_list:
		if pc.get("domain", "") == domain_name:
			pc["amount"] = pc.get("amount", 0) + amount
			return
	power_list.append({"domain": domain_name, "amount": amount})


static func cost_to_string(cost: Dictionary) -> String:
	var parts: Array[String] = []
	var energy = cost.get("energy", 0)
	if energy > 0:
		parts.append("%d ENG" % energy)
	for pc in cost.get("power", []):
		parts.append("%d %s" % [pc.get("amount", 1), CardDefinition._domain_abbr(pc.get("domain", ""))])
	if cost.get("exhaust", false):
		parts.append("EXH")
	if cost.get("discard", 0) > 0:
		parts.append("DISCARD:%d" % cost.get("discard", 0))
	if cost.get("recycle", 0) > 0:
		parts.append("RECYCLE:%d" % cost.get("recycle", 0))
	return " + ".join(parts) if not parts.is_empty() else "free"
