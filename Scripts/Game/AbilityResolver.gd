class_name AbilityResolver

# Resolves effect_type handlers per §2.5 of the card data schema.
# Returns an array of log line strings.

func resolve_ability(ability: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var effect_type: String = ability.get("effect_type", "")
	var params: Dictionary = ability.get("effect_params", {})

	match effect_type:
		"add_energy":
			log_lines.append_array(_add_energy(params, source, gs))
		"add_power":
			log_lines.append_array(_add_power(params, source, gs))
		"draw":
			log_lines.append_array(_draw(params, source, gs))
		"deal_damage":
			log_lines.append_array(_deal_damage(params, source, target, gs))
		"heal":
			log_lines.append_array(_heal(params, source, target, gs))
		"kill":
			log_lines.append_array(_kill(params, source, target, gs))
		"give_might":
			log_lines.append_array(_give_might(params, source, target, gs))
		"give_keyword":
			log_lines.append_array(_give_keyword(params, source, target, gs))
		"buff_unit":
			log_lines.append_array(_buff_unit(params, source, target, gs))
		"stun_unit":
			log_lines.append_array(_stun_unit(params, source, target, gs))
		"move_unit":
			log_lines.append_array(_move_unit(params, source, target, gs))
		"recycle":
			log_lines.append_array(_recycle(params, source, gs))
		"discard":
			log_lines.append_array(_discard(params, source, gs))
		"channel_rune":
			log_lines.append_array(_channel_rune(params, source, gs))
		"ready_permanent":
			log_lines.append_array(_ready_permanent(params, source, target, gs))
		"play_token":
			log_lines.append_array(_play_token(params, source, gs))
		"gain_points":
			log_lines.append_array(_gain_points(params, source, gs))
		"counter_spell":
			log_lines.append_array(_counter_spell(params, source, target, gs))
		"predict":
			log_lines.append_array(_predict(params, source, gs))
		"return_to_hand":
			log_lines.append_array(_return_to_hand(params, source, target, gs))
		"cost_reduction":
			pass  # Handled at cost calculation time, not resolution
		"attach":
			log_lines.append_array(_attach(params, source, target, gs))
		_:
			log_lines.append("> [INFO] Unhandled effect type: %s" % effect_type)

	return log_lines


# ── Individual effect handlers ──────────────────────────────────────────────

func _add_energy(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var amount: int = params.get("amount", 1)
	gs.players[source.owner_index].rune_pool.add_energy(amount)
	return ["> P%d added %d energy to pool" % [source.owner_index + 1, amount]]


func _add_power(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var domain_name: String = params.get("domain", "")
	var amount: int = params.get("amount", 1)
	gs.players[source.owner_index].rune_pool.add_power(domain_name, amount)
	return ["> P%d added %d %s power to pool" % [
		source.owner_index + 1, amount, CardDefinition._domain_abbr(domain_name)
	]]


func _draw(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var amount: int = params.get("amount", 1)
	var owner: int = source.owner_index
	var ps: PlayerState = gs.players[owner]
	for _i in range(amount):
		if ps.deck.is_empty():
			if ps.trash.is_empty():
				log_lines.append("> P%d cannot draw — deck and trash both empty" % (owner + 1))
				break
			ps.shuffle_trash_into_deck()
			var opp = 1 - owner
			gs.players[opp].score += 1
			log_lines.append("> P%d Burn Out! P%d gains 1 point. Score: P1=%d, P2=%d" % [
				owner + 1, opp + 1, gs.players[0].score, gs.players[1].score
			])
		var drawn = ps.draw_card()
		if drawn:
			log_lines.append("> P%d drew a card (hand: %d)" % [owner + 1, ps.hand.size()])
	return log_lines


func _deal_damage(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var amount: int = params.get("amount", 1)
	var targeting: String = params.get("targeting", "choose_one")

	if target == null:
		log_lines.append("[INFO] deal_damage: no target provided")
		return log_lines

	target.add_damage(amount)
	log_lines.append("> %s dealt %d damage to %s (total: %d/%d)" % [
		source.display_name(), amount, target.display_name(),
		target.damage, target.get_base_might()
	])
	return log_lines


func _heal(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	target.heal_all()
	return ["> %s healed" % target.display_name()]


func _kill(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	gs.board.remove_unit_from_battlefield(target)
	gs.players[target.owner_index].move_to_trash(target)
	return ["> %s was killed by %s" % [target.display_name(), source.display_name()]]


func _give_might(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	var amount: int = params.get("amount", 1)
	var duration: String = params.get("duration", "turn")
	if duration == "turn":
		target.temp_might_bonus += amount
	return ["> %s +%d Might (%s)" % [target.display_name(), amount, duration]]


func _give_keyword(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	var kw_id: String = params.get("keyword", "")
	var kw_val: int = params.get("value", 1)
	var duration: String = params.get("duration", "turn")
	if duration == "turn":
		target.temp_keywords.append({"id": kw_id, "value": kw_val})
	return ["> %s gained %s" % [target.display_name(), kw_id]]


func _buff_unit(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	target.add_buff()
	return ["> %s gained a Buff counter (+1 Might)" % target.display_name()]


func _stun_unit(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	target.apply_stun()
	return ["> %s is Stunned" % target.display_name()]


func _move_unit(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	var dest: String = params.get("destination", "base")
	# Complex movement handled separately via command layer
	return ["> Move effect: %s → %s" % [target.display_name(), dest]]


func _recycle(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var from_zone: String = params.get("from", "trash")
	var amount: int = params.get("amount", 1)
	var owner: int = source.owner_index
	var ps: PlayerState = gs.players[owner]
	if from_zone == "trash" and not ps.trash.is_empty():
		for _i in range(mini(amount, ps.trash.size())):
			var card = ps.trash[ps.trash.size() - 1]
			ps.move_to_hand(card)
			log_lines.append("> P%d recycled %s to hand" % [owner + 1, card.display_name()])
	return log_lines


func _discard(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var log_lines: Array[String] = []
	var amount: int = params.get("amount", 1)
	var owner: int = source.owner_index
	var ps: PlayerState = gs.players[owner]
	for _i in range(mini(amount, ps.hand.size())):
		var card = ps.hand[0]
		ps.move_to_trash(card)
		log_lines.append("> P%d discarded %s" % [owner + 1, card.display_name()])
	return log_lines


func _channel_rune(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var amount: int = params.get("amount", 1)
	var log_lines: Array[String] = []
	var owner: int = source.owner_index
	var ps: PlayerState = gs.players[owner]
	for _i in range(amount):
		var rune = ps.channel_rune()
		if rune:
			log_lines.append("> P%d channeled an extra rune" % (owner + 1))
	return log_lines


func _ready_permanent(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	target.ready()
	return ["> %s is now Ready" % target.display_name()]


func _play_token(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var token_type: String = params.get("token_type", "recruit_1m")
	var location: String = params.get("location", "base")
	var owner: int = source.owner_index
	var ps: PlayerState = gs.players[owner]
	var token_def = CardLoader.get_card(token_type)
	if token_def == null:
		return ["> [ERROR] Unknown token type: %s" % token_type]
	var token = ps.create_instance(token_def)
	token.location = location
	ps.base_permanents.append(token)
	return ["> P%d created a token: %s at %s" % [owner + 1, token.display_name(), location]]


func _gain_points(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var amount: int = params.get("amount", 1)
	var owner: int = source.owner_index
	gs.players[owner].score += amount
	return ["> P%d gained %d point(s). Score: P1=%d, P2=%d" % [
		owner + 1, amount, gs.players[0].score, gs.players[1].score
	]]


func _counter_spell(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	# Counter the top item on the chain (or specified target)
	if gs.chain.is_empty():
		return ["> [ERROR] Nothing on the chain to counter"]
	var item = gs.chain[gs.chain.size() - 1]
	# Mark as countered by clearing it
	gs.chain.erase(item)
	return ["> %s countered %s" % [source.display_name(), item.describe()]]


func _predict(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var amount: int = params.get("amount", 1)
	var owner: int = source.owner_index
	var ps: PlayerState = gs.players[owner]
	if ps.deck.is_empty():
		return ["> P%d's deck is empty — cannot predict" % (owner + 1)]
	var look: Array = []
	for i in range(mini(amount, ps.deck.size())):
		look.append(ps.deck[i].display_name())
	return ["[INFO] P%d looks at top of deck: %s" % [owner + 1, ", ".join(look)]]


func _return_to_hand(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	var owner: int = target.owner_index
	gs.board.remove_unit_from_battlefield(target)
	gs.players[owner].move_to_hand(target)
	return ["> %s returned to P%d's hand" % [target.display_name(), owner + 1]]


func _attach(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	if source.definition.card_type != "gear":
		return ["> [ERROR] Only Gear can be attached"]
	# Detach from any previous host
	if source.attached_to != null:
		source.attached_to.attached_gear.erase(source)
	source.attached_to = target
	if not source in target.attached_gear:
		target.attached_gear.append(source)
	# Move gear's location to match the unit's location
	source.location = target.location
	source.battlefield_index = target.battlefield_index
	return ["> %s attached to %s" % [source.display_name(), target.display_name()]]
