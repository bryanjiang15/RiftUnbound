class_name CostCalculator

# Computes the total cost of playing a card or activating an ability,
# applying all modifiers (Legion reduction, Deflect surcharge, Accelerate opt-in).

static func compute_play_cost(
	card: CardInstance,
	player_index: int,
	gs: GameState,
	use_accelerate: bool = false
) -> Dictionary:
	var energy = card.definition.energy_cost
	var power = _copy_power_cost(card.definition.power_cost)

	# Legion: reduce own cost by 2 if controller played another card this turn
	if card.has_keyword("legion"):
		var ps: PlayerState = gs.players[player_index]
		if ps.cards_played_this_turn > 0:
			energy = maxi(0, energy - 2)

	# Accelerate: optional +1 energy + 1 power of card's domain to enter Ready
	if use_accelerate and card.has_keyword("accelerate"):
		energy += 1
		if not card.definition.domain.is_empty():
			var domain = card.definition.domain[0]
			_add_power_cost(power, domain, 1)

	# Costs can never go below 0
	energy = maxi(0, energy)

	return {"energy": energy, "power": power, "accelerate": use_accelerate}


static func compute_ability_cost(
	ability: Dictionary,
	source: CardInstance,
	target: CardInstance,
	gs: GameState
) -> Dictionary:
	var cost = ability.get("cost", {})
	var energy = cost.get("energy", 0)
	var power = _copy_power_cost(cost.get("power", []))

	# Deflect: if targeting an enemy unit with Deflect, add extra power cost
	if target != null and target.has_keyword("deflect"):
		var deflect_val = target.get_keyword_value("deflect")
		if source.owner_index != target.owner_index:
			if not target.definition.domain.is_empty():
				_add_power_cost(power, target.definition.domain[0], deflect_val)
			else:
				energy += deflect_val

	return {"energy": energy, "power": power, "exhaust": cost.get("exhaust", false), "recycle_self": cost.get("recycle_self", false)}


static func can_afford(player_index: int, cost: Dictionary, gs: GameState) -> bool:
	var ps: PlayerState = gs.players[player_index]
	return ps.rune_pool.can_pay(cost.get("energy", 0), cost.get("power", []))


static func pay_cost(player_index: int, cost: Dictionary, source: CardInstance, gs: GameState) -> void:
	var ps: PlayerState = gs.players[player_index]
	ps.rune_pool.pay(cost.get("energy", 0), cost.get("power", []))
	if cost.get("exhaust", false) and source != null:
		source.exhaust()
	if cost.get("recycle_self", false) and source != null:
		ps.remove_rune(source)
		ps.recycle_to_bottom(source, true)


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
	return " + ".join(parts) if not parts.is_empty() else "free"
