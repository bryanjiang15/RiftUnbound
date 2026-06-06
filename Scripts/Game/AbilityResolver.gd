class_name AbilityResolver

# Resolves effect_type handlers per §2.5 of the card data schema.
# Returns an array of log line strings.

func resolve_ability(ability: Dictionary, source: Variant, target: CardInstance, gs: GameState, ctx: Dictionary = {}) -> Array:
	var log_lines: Array[String] = []
	var effect_type: String = ability.get("effect_type", "")
	var params: Dictionary = ability.get("effect_params", {})
	var card_source: CardInstance = source if source is CardInstance else null
	var owner_pi = card_source.owner_index if card_source else int(ctx.get("player_index", 0))

	match effect_type:
		"add_energy":
			log_lines.append_array(_add_energy(params, card_source, gs, owner_pi))
		"add_power":
			log_lines.append_array(_add_power(params, card_source, gs, owner_pi))
		"draw":
			log_lines.append_array(_draw(params, card_source, gs, owner_pi))
		"deal_damage":
			log_lines.append_array(_deal_damage(params, card_source, target, gs))
		"heal":
			log_lines.append_array(_heal(params, target))
		"kill":
			log_lines.append_array(_kill(card_source, target, gs))
		"give_might":
			log_lines.append_array(_give_might(params, target))
		"give_keyword":
			log_lines.append_array(_give_keyword(params, target))
		"buff_unit":
			log_lines.append_array(_buff_unit(target))
		"stun_unit":
			log_lines.append_array(_stun_unit(target))
		"move_unit":
			log_lines.append_array(_move_unit(params, target, gs))
		"move_unit_to_base":
			log_lines.append_array(_move_unit_to_base(target, gs))
		"recycle":
			log_lines.append_array(_recycle(params, card_source, gs, owner_pi))
		"discard":
			log_lines.append_array(_discard(params, card_source, gs, owner_pi, ctx))
		"discard_then_draw":
			log_lines.append_array(_discard_then_draw(params, card_source, gs, owner_pi, ctx))
		"channel_rune":
			log_lines.append_array(_channel_rune(params, gs, owner_pi))
		"ready_permanent":
			log_lines.append_array(_ready_permanent(target))
		"ready_runes":
			log_lines.append_array(_ready_runes(params, gs, owner_pi))
		"play_token":
			log_lines.append_array(_play_token(params, gs, owner_pi))
		"gain_points":
			log_lines.append_array(_gain_points(params, gs, owner_pi))
		"counter_spell":
			log_lines.append_array(_counter_spell(card_source, gs))
		"predict":
			log_lines.append_array(_predict(params, gs, owner_pi))
		"return_to_hand":
			log_lines.append_array(_return_to_hand(target, gs))
		"enter_ready":
			if card_source:
				log_lines.append_array(_enter_ready(card_source))
		"return_from_trash":
			log_lines.append_array(_return_from_trash(params, gs, owner_pi, ctx))
		"other_friendly_units_enter_ready":
			log_lines.append_array(_other_friendly_enter_ready(card_source, gs))
		"gain_keywords":
			log_lines.append_array(_gain_keywords(params, card_source))
		"play_self":
			log_lines.append_array(_play_self(ability, card_source, gs, ctx))
		"deal_damage_equal_to_discarded_energy_cost":
			log_lines.append_array(_deal_damage_discarded_cost(params, card_source, target, gs, owner_pi, ctx))
		"cost_reduction":
			pass
		"attach":
			log_lines.append_array(_attach(card_source, target))
		_:
			log_lines.append("> [INFO] Unhandled effect type: %s" % effect_type)

	return log_lines


func _add_energy(params: Dictionary, source: CardInstance, gs: GameState, owner: int) -> Array:
	var amount: int = params.get("amount", 1)
	gs.players[owner].rune_pool.add_energy(amount)
	return ["> P%d added %d energy to pool" % [owner + 1, amount]]


func _add_power(params: Dictionary, source: CardInstance, gs: GameState, owner: int) -> Array:
	var domain_name: String = params.get("domain", "")
	var amount: int = params.get("amount", 1)
	gs.players[owner].rune_pool.add_power(domain_name, amount)
	return ["> P%d added %d %s power to pool" % [owner + 1, amount, CardDefinition._domain_abbr(domain_name)]]


func _draw(params: Dictionary, source: CardInstance, gs: GameState, owner: int) -> Array:
	var log_lines: Array[String] = []
	var amount: int = params.get("amount", 1)
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
	if target == null:
		return ["[INFO] deal_damage: no target provided"]
	var amount: int = params.get("amount", 1)
	target.add_damage(amount)
	var src_name = source.display_name() if source else "Effect"
	return ["> %s dealt %d damage to %s (total: %d/%d)" % [
		src_name, amount, target.display_name(), target.damage, target.get_base_might()
	]]


func _heal(params: Dictionary, target: CardInstance) -> Array:
	if target == null:
		return []
	var amount = params.get("amount", "all")
	if amount == "all" or int(str(amount)) >= target.damage:
		target.heal_all()
	else:
		target.damage = maxi(0, target.damage - int(amount))
	return ["> %s healed" % target.display_name()]


func _kill(source: CardInstance, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	gs.board.remove_unit_from_battlefield(target)
	gs.players[target.owner_index].move_to_trash(target)
	var src_name = source.display_name() if source else "Effect"
	return ["> %s was killed by %s" % [target.display_name(), src_name]]


func _give_might(params: Dictionary, target: CardInstance) -> Array:
	if target == null:
		return []
	var amount: int = params.get("amount", 1)
	var duration: String = params.get("duration", "turn")
	if duration == "turn":
		target.temp_might_bonus += amount
	return ["> %s +%d Might (%s)" % [target.display_name(), amount, duration]]


func _give_keyword(params: Dictionary, target: CardInstance) -> Array:
	if target == null:
		return []
	var kw = params.get("keyword", "")
	var kw_id: String = kw.get("id", kw) if kw is Dictionary else str(kw)
	var kw_val: int = kw.get("value", params.get("value", 1)) if kw is Dictionary else params.get("value", 1)
	var duration: String = params.get("duration", "turn")
	if duration == "turn" or duration.is_empty():
		target.temp_keywords.append({"id": kw_id, "value": kw_val})
	return ["> %s gained %s" % [target.display_name(), kw_id]]


func _buff_unit(target: CardInstance) -> Array:
	if target == null:
		return []
	target.add_buff()
	return ["> %s gained a Buff counter (+1 Might)" % target.display_name()]


func _stun_unit(target: CardInstance) -> Array:
	if target == null:
		return []
	target.apply_stun()
	return ["> %s is Stunned" % target.display_name()]


func _move_unit(params: Dictionary, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	return _move_unit_to_base(target, gs)


func _move_unit_to_base(target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	var owner = target.owner_index
	var ps = gs.players[owner]
	if target.is_at_battlefield():
		gs.board.remove_unit_from_battlefield(target)
	else:
		ps.base_permanents.erase(target)
	target.location = "base"
	target.is_exhausted = true
	ps.base_permanents.append(target)
	return ["> %s moved to base" % target.display_name()]


func _recycle(params: Dictionary, source: CardInstance, gs: GameState, owner: int) -> Array:
	var log_lines: Array[String] = []
	var from_zone: String = params.get("from", "trash")
	var amount: int = params.get("amount", 1)
	var ps: PlayerState = gs.players[owner]
	if from_zone == "trash":
		for _i in range(mini(amount, ps.trash.size())):
			var card = ps.trash[ps.trash.size() - 1]
			ps.move_to_hand(card)
			log_lines.append("> P%d recycled %s to hand" % [owner + 1, card.display_name()])
	return log_lines


func _discard(params: Dictionary, source: CardInstance, gs: GameState, owner: int, ctx: Dictionary) -> Array:
	var amount: int = params.get("amount", 1)
	var ps: PlayerState = gs.players[owner]
	var controller: GameController = ctx.get("controller")
	if controller != null and amount > 0 and not ps.hand.is_empty():
		return controller.begin_discard(owner, amount, ctx.get("continuation", {}), source, ctx.get("ability", {}))
	return _discard_sync(amount, source, gs, owner, ctx)


func _discard_sync(amount: int, source: CardInstance, gs: GameState, owner: int, ctx: Dictionary) -> Array:
	var log_lines: Array[String] = []
	var ps: PlayerState = gs.players[owner]
	var controller: GameController = ctx.get("controller")
	for _i in range(amount):
		if ps.hand.is_empty():
			break
		var card = ps.hand[0]
		ps.move_to_trash(card)
		ps.cards_discarded_count += 1
		ps.discarded_this_turn.append(card)
		log_lines.append("> P%d discarded %s" % [owner + 1, card.display_name()])
		if controller != null and controller.trigger_dispatcher:
			log_lines.append_array(controller.trigger_dispatcher.emit("on_discard", {
				"discarded_card": card, "player_index": owner, "controller": controller
			}, gs, controller))
			if not gs.pending_prompt.is_empty():
				return log_lines
	return log_lines


func _discard_then_draw(params: Dictionary, source: CardInstance, gs: GameState, owner: int, ctx: Dictionary) -> Array:
	var discard_n = int(params.get("discard_amount", 1))
	var draw_n = int(params.get("draw_amount", discard_n))
	var controller: GameController = ctx.get("controller")
	if controller != null and discard_n > 0 and not gs.players[owner].hand.is_empty():
		var draw_ctx = ctx.duplicate()
		draw_ctx["continuation"] = {
			"kind": "discard_then_draw",
			"draw_amount": draw_n,
			"owner": owner,
		}
		return controller.begin_discard(owner, discard_n, draw_ctx["continuation"], source, ctx.get("ability", {}))
	var log_lines: Array[String] = []
	log_lines.append_array(_discard_sync(discard_n, source, gs, owner, ctx))
	log_lines.append_array(_draw({"amount": draw_n}, source, gs, owner))
	return log_lines


func _channel_rune(params: Dictionary, gs: GameState, owner: int) -> Array:
	var amount: int = params.get("amount", 1)
	var log_lines: Array[String] = []
	var ps: PlayerState = gs.players[owner]
	for _i in range(amount):
		if ps.channel_rune():
			log_lines.append("> P%d channeled an extra rune" % (owner + 1))
	return log_lines


func _ready_permanent(target: CardInstance) -> Array:
	if target == null:
		return []
	target.ready()
	return ["> %s is now Ready" % target.display_name()]


func _ready_runes(params: Dictionary, gs: GameState, owner: int) -> Array:
	var amount: int = params.get("amount", 1)
	var ps: PlayerState = gs.players[owner]
	var count = 0
	for rune in ps.channeled_runes:
		if count >= amount:
			break
		rune.ready()
		count += 1
	return ["> P%d readied %d rune(s)" % [owner + 1, count]]


func _play_token(params: Dictionary, gs: GameState, owner: int) -> Array:
	var token_type: String = params.get("token_type", "recruit_1m")
	var location: String = params.get("location", "base")
	var ps: PlayerState = gs.players[owner]
	var token_def = CardLoader.get_card(token_type)
	if token_def == null:
		return ["> [ERROR] Unknown token type: %s" % token_type]
	var token = ps.create_instance(token_def)
	token.location = location
	ps.base_permanents.append(token)
	return ["> P%d created a token: %s at %s" % [owner + 1, token.display_name(), location]]


func _gain_points(params: Dictionary, gs: GameState, owner: int) -> Array:
	var amount: int = params.get("amount", 1)
	gs.players[owner].score += amount
	return ["> P%d gained %d point(s). Score: P1=%d, P2=%d" % [
		owner + 1, amount, gs.players[0].score, gs.players[1].score
	]]


func _counter_spell(source: CardInstance, gs: GameState) -> Array:
	if gs.chain.is_empty():
		return ["> [ERROR] Nothing on the chain to counter"]
	var item = gs.chain[gs.chain.size() - 1]
	gs.chain.erase(item)
	var src_name = source.display_name() if source else "Effect"
	return ["> %s countered %s" % [src_name, item.describe()]]


func _predict(params: Dictionary, gs: GameState, owner: int) -> Array:
	var amount: int = params.get("amount", 1)
	var ps: PlayerState = gs.players[owner]
	if ps.deck.is_empty():
		return ["> P%d's deck is empty — cannot predict" % (owner + 1)]
	var look: Array = []
	for i in range(mini(amount, ps.deck.size())):
		look.append(ps.deck[i].display_name())
	return ["[INFO] P%d looks at top of deck: %s" % [owner + 1, ", ".join(look)]]


func _return_to_hand(target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	var owner: int = target.owner_index
	gs.board.remove_unit_from_battlefield(target)
	gs.players[owner].base_permanents.erase(target)
	gs.players[owner].move_to_hand(target)
	return ["> %s returned to P%d's hand" % [target.display_name(), owner + 1]]


func _enter_ready(source: CardInstance) -> Array:
	source.ready()
	return ["> %s enters ready" % source.display_name()]


func _return_from_trash(params: Dictionary, gs: GameState, owner: int, ctx: Dictionary) -> Array:
	var ps: PlayerState = gs.players[owner]
	var target_type: String = params.get("target", "any")
	for i in range(ps.trash.size() - 1, -1, -1):
		var card = ps.trash[i]
		if target_type == "any" or card.definition.card_type == target_type:
			ps.move_to_hand(card)
			return ["> P%d returned %s from trash to hand" % [owner + 1, card.display_name()]]
	return ["> P%d has no %s in trash to return" % [owner + 1, target_type]]


func _other_friendly_enter_ready(source: CardInstance, gs: GameState) -> Array:
	if source == null:
		return []
	var owner = source.owner_index
	var ps = gs.players[owner]
	var count = 0
	for u in ps.get_units_at_base():
		if u != source:
			u.ready()
			count += 1
	for u in gs.board.get_all_units_on_board(owner):
		if u != source:
			u.ready()
			count += 1
	return ["> %d other friendly unit(s) enter Ready" % count]


func _gain_keywords(params: Dictionary, source: CardInstance) -> Array:
	if source == null:
		return []
	for kw in params.get("keywords", []):
		source.passive_keywords.append(kw)
	return ["> %s gained passive keywords" % source.display_name()]


func _play_self(ability: Dictionary, source: CardInstance, gs: GameState, ctx: Dictionary) -> Array:
	if source == null:
		return []
	var owner = source.owner_index
	var ps = gs.players[owner]
	ps.trash.erase(source)
	source.location = "base"
	source.is_exhausted = true
	ps.base_permanents.append(source)
	return ["> %s played itself from discard" % source.display_name()]


func _deal_damage_discarded_cost(params: Dictionary, source: CardInstance, target: CardInstance, gs: GameState, owner: int, ctx: Dictionary) -> Array:
	var log_lines: Array[String] = []
	var ps = gs.players[owner]
	var energy = 0
	if not ps.discarded_this_turn.is_empty():
		energy = ps.discarded_this_turn[ps.discarded_this_turn.size() - 1].definition.energy_cost
	else:
		return ["> P%d has no discarded card for damage" % (owner + 1)]
	if target == null:
		return log_lines
	target.add_damage(energy)
	log_lines.append("> Dealt %d damage to %s (discarded card cost)" % [energy, target.display_name()])
	return log_lines


func _attach(source: CardInstance, target: CardInstance) -> Array:
	if target == null or source == null:
		return []
	if source.definition.card_type != "gear":
		return ["> [ERROR] Only Gear can be attached"]
	if source.attached_to != null:
		source.attached_to.attached_gear.erase(source)
	source.attached_to = target
	if not source in target.attached_gear:
		target.attached_gear.append(source)
	source.location = target.location
	source.battlefield_index = target.battlefield_index
	return ["> %s attached to %s" % [source.display_name(), target.display_name()]]
