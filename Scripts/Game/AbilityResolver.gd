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
			log_lines.append_array(_give_might(params, target, gs, owner_pi))
		"give_keyword":
			log_lines.append_array(_give_keyword(params, target))
		"buff_unit":
			log_lines.append_array(_buff_unit(target))
		"stun_unit":
			log_lines.append_array(_stun_unit(target))
		"move_unit":
			log_lines.append_array(_move_unit(params, target, gs, ctx))
		"move_unit_to_base":
			log_lines.append_array(_move_unit_to_base(target, gs))
		"recycle":
			log_lines.append_array(_recycle(params, card_source, gs, owner_pi))
		"recycle_from_trash":
			log_lines.append_array(_recycle_from_trash(params, gs, owner_pi))
		"discard":
			log_lines.append_array(_discard(params, card_source, gs, owner_pi, ctx))
		"discard_then_draw":
			log_lines.append_array(_discard_then_draw(params, card_source, gs, owner_pi, ctx))
		"channel_rune":
			log_lines.append_array(_channel_rune(params, gs, owner_pi))
		"channel_rune_or_draw":
			log_lines.append_array(_channel_rune_or_draw(params, gs, owner_pi))
		"units_enter_ready_this_turn":
			log_lines.append_array(_units_enter_ready_this_turn(gs, owner_pi))
		"give_might_with_alone_bonus":
			log_lines.append_array(_give_might_with_alone_bonus(params, target, gs))
		"deal_damage_all_enemies_in_combat":
			log_lines.append_array(_deal_damage_all_enemies_in_combat(params, card_source, gs))
		"fight_chosen_units":
			log_lines.append_array(_fight_chosen_units(card_source, target, ctx, gs))
		"ready_permanent":
			log_lines.append_array(_ready_permanent(target))
		"ready_runes":
			log_lines.append_array(_ready_runes(params, gs, owner_pi))
		"play_token":
			log_lines.append_array(_play_token(params, card_source, gs, owner_pi))
		"gain_points":
			log_lines.append_array(_gain_points(params, gs, owner_pi))
		"counter_spell":
			log_lines.append_array(_counter_spell(card_source, gs, params))
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
		"death_replacement_recall":
			log_lines.append_array(_death_replacement_recall(target, gs))
		"prevent_damage":
			log_lines.append_array(_prevent_damage(params, gs))
		"choose_draw_or_channel":
			log_lines.append_array(_choose_draw_or_channel(params, card_source, gs, owner_pi, ctx))
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
	if gs.prevent_spell_ability_damage:
		return ["> Damage from spells/abilities prevented"]
	var amount: int = params.get("amount", 1)
	target.add_damage(amount)
	var src_name = source.display_name() if source else "Effect"
	return ["> %s dealt %d damage to %s (total: %d/%d)" % [
		src_name, amount, target.display_name(), target.damage, target.get_current_might()
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


func _give_might(params: Dictionary, target: CardInstance, gs: GameState, owner: int) -> Array:
	if target == null and params.get("target", "") == "all_enemy_units":
		var log_lines: Array[String] = []
		for enemy in gs.board.get_all_units_on_board(1 - owner):
			log_lines.append_array(_give_might_to_one(params, enemy))
		return log_lines if not log_lines.is_empty() else ["> No enemy units to affect"]
	return _give_might_to_one(params, target)


func _give_might_to_one(params: Dictionary, target: CardInstance) -> Array:
	if target == null:
		return []
	var amount: int = params.get("amount", 1)
	var duration: String = params.get("duration", "turn")
	if params.has("minimum_might") and amount < 0:
		var minimum := int(params.get("minimum_might", 1))
		amount = maxi(amount, minimum - target.get_current_might())
	if duration == "turn":
		target.temp_might_bonus += amount
	var sign := "+" if amount >= 0 else ""
	return ["> %s %s%d Might (%s)" % [target.display_name(), sign, amount, duration]]


func _give_keyword(params: Dictionary, target: CardInstance) -> Array:
	if target == null:
		return []
	var kw = params.get("keyword", "")
	var kw_id: String = kw.get("id", kw) if kw is Dictionary else str(kw)
	var kw_val: int = kw.get("value", params.get("value", 1)) if kw is Dictionary else params.get("value", 1)
	var duration: String = params.get("duration", "turn")
	if duration.is_empty():
		duration = "turn"
	if kw_id == "temporary" and duration == "turn":
		duration = "until_beginning"
	# "turn" effects clear at end-of-turn cleanup; "combat" effects clear when the
	# current combat resolves (CombatProcessor.finalize_combat). Temporary lasts
	# until the start of the marked permanent's controller's next Beginning Phase.
	if duration == "turn" or duration == "combat" or duration == "until_beginning":
		target.temp_keywords.append({"id": kw_id, "value": kw_val, "duration": duration})
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


func _move_unit(params: Dictionary, target: CardInstance, gs: GameState, ctx: Dictionary = {}) -> Array:
	if target == null:
		return []
	var destination: String = str(params.get("destination", "base"))
	if destination == "choose":
		var controller: GameController = ctx.get("controller")
		if controller != null:
			var choices: Array[String] = ["base"]
			for bf in gs.board.battlefields:
				if target.is_at_battlefield() and bf.battlefield_id == gs.board.battlefields[target.battlefield_index].battlefield_id:
					continue
				choices.append(bf.battlefield_id)
			# Vilemaw: cannot choose base from a no_move_to_base battlefield.
			if target.is_at_battlefield() and _battlefield_blocks_move_to_base(gs, target.battlefield_index):
				choices.erase("base")
			gs.pending_prompt = {
				"player_index": int(ctx.get("player_index", target.owner_index)),
				"type": "choose_battlefield",
				"valid_choices": choices,
				"move_destination_resume": {
					"target": target,
					"params": params,
					"source": ctx.get("source", null),
					"chain_source_card": ctx.get("chain_source_card", null),
				},
				"prompt": "[PROMPT] Choose destination for %s — use: choose <%s>" % [
					target.display_name(), "|".join(choices)
				],
			}
			return [gs.pending_prompt["prompt"]]
		destination = "base"
	if destination == "base" or destination.is_empty():
		return _move_unit_to_base(target, gs)
	var bf_idx = gs.board.get_battlefield_index(destination)
	if bf_idx < 0:
		return ["[INFO] move_unit: unknown destination %s" % destination]
	if target.is_at_battlefield() and target.battlefield_index == bf_idx:
		return ["> %s is already at %s" % [target.display_name(), destination]]
	var owner = target.owner_index
	var ps = gs.players[owner]
	if target.is_at_battlefield():
		gs.board.remove_unit_from_battlefield(target)
	else:
		ps.base_permanents.erase(target)
	gs.board.add_unit_to_battlefield(target, bf_idx)
	var log_lines: Array[String] = ["> %s moved to %s" % [target.display_name(), destination]]
	# Same contested rules as a normal Move: the effect controller is the aggressor.
	var mover_pi = int(ctx.get("player_index", owner))
	var bf = gs.board.battlefields[bf_idx]
	if bf.controller_index != mover_pi or not bf.units[1 - mover_pi].is_empty():
		bf.is_contested = true
		gs.attacker_player_index = mover_pi
		log_lines.append("> %s is now Contested" % bf.display_name)
	return log_lines


func _move_unit_to_base(target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return []
	if target.is_at_battlefield() and _battlefield_blocks_move_to_base(gs, target.battlefield_index):
		return ["> %s cannot move to base from %s" % [
			target.display_name(), gs.board.battlefields[target.battlefield_index].display_name
		]]
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


static func _battlefield_blocks_move_to_base(gs: GameState, bf_idx: int) -> bool:
	if bf_idx < 0 or bf_idx >= gs.board.battlefields.size():
		return false
	var bf = gs.board.battlefields[bf_idx]
	if bf.card_def == null:
		return false
	for kw in bf.card_def.keywords:
		if kw.get("id", "") == "no_move_to_base":
			return true
	return false


func _prevent_damage(params: Dictionary, gs: GameState) -> Array:
	var source_filter: String = str(params.get("source", "spells_and_abilities"))
	if source_filter == "spells_and_abilities" or source_filter == "all":
		gs.prevent_spell_ability_damage = true
		return ["> Damage from spells and abilities is prevented this turn"]
	return ["> [INFO] prevent_damage: unsupported source %s" % source_filter]


func _choose_draw_or_channel(params: Dictionary, source: CardInstance, gs: GameState, owner: int, ctx: Dictionary) -> Array:
	var controller: GameController = ctx.get("controller")
	if controller == null:
		# Simulation fallback: prefer channel if possible, else draw.
		var ps: PlayerState = gs.players[owner]
		if not ps.rune_deck.is_empty():
			return _channel_rune({
				"amount": int(params.get("channel_amount", 1)),
				"exhausted": params.get("exhausted", true),
			}, gs, owner)
		return _draw({"amount": int(params.get("draw_amount", 1))}, source, gs, owner)
	gs.pending_prompt = {
		"player_index": owner,
		"type": "choose_mode",
		"valid_choices": ["draw", "channel"],
		"mode_resume": {
			"params": params,
			"source": source,
			"owner": owner,
		},
		"prompt": "[PROMPT] Choose draw or channel — use: choose draw or choose channel",
	}
	return [gs.pending_prompt["prompt"]]


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


func _recycle_from_trash(params: Dictionary, gs: GameState, owner: int) -> Array:
	var log_lines: Array[String] = []
	var amount: int = params.get("amount", 1)
	var ps: PlayerState = gs.players[owner]
	for _i in range(mini(amount, ps.trash.size())):
		var card = ps.trash[ps.trash.size() - 1]
		ps.recycle_to_bottom(card, false)
		log_lines.append("> P%d recycled %s from trash to deck" % [owner + 1, card.display_name()])
	if log_lines.is_empty():
		log_lines.append("> P%d has no cards in trash to recycle" % (owner + 1))
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
	var exhausted: bool = params.get("exhausted", false)
	var log_lines: Array[String] = []
	var ps: PlayerState = gs.players[owner]
	for _i in range(amount):
		if ps.channel_rune(exhausted):
			log_lines.append("> P%d channeled an extra rune%s" % [
				owner + 1, " (exhausted)" if exhausted else ""
			])
	return log_lines


func _channel_rune_or_draw(params: Dictionary, gs: GameState, owner: int) -> Array:
	# Channel N rune(s); if the rune deck is empty (can't channel), draw instead.
	var channel_amount: int = params.get("channel_amount", params.get("amount", 1))
	var exhausted: bool = params.get("exhausted", false)
	var draw_amount: int = params.get("draw_amount", 1)
	var ps: PlayerState = gs.players[owner]
	if ps.rune_deck.is_empty():
		return _draw({"amount": draw_amount}, null, gs, owner)
	return _channel_rune({"amount": channel_amount, "exhausted": exhausted}, gs, owner)


func _units_enter_ready_this_turn(gs: GameState, owner: int) -> Array:
	gs.players[owner].units_enter_ready_this_turn = true
	return ["> P%d: units played this turn enter ready" % (owner + 1)]


func _give_might_with_alone_bonus(params: Dictionary, target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return ["[INFO] give_might_with_alone_bonus: no target provided"]
	var amount: int = params.get("amount", 1)
	var alone_bonus: int = params.get("alone_bonus", 0)
	var total := amount
	# "the only unit you control there" — count friendly units at target's location.
	if alone_bonus != 0 and _is_only_friendly_unit_here(target, gs):
		total += alone_bonus
	target.temp_might_bonus += total
	return ["> %s +%d Might (this turn)" % [target.display_name(), total]]


func _is_only_friendly_unit_here(unit: CardInstance, gs: GameState) -> bool:
	var owner := unit.owner_index
	if unit.is_at_battlefield():
		var bf = gs.board.battlefields[unit.battlefield_index]
		return bf.units[owner].size() == 1
	# At base: "there" is the base; alone if it's the only base unit.
	return gs.players[owner].get_units_at_base().size() == 1


func _deal_damage_all_enemies_in_combat(params: Dictionary, source: CardInstance, gs: GameState) -> Array:
	var amount: int = params.get("amount", 1)
	if gs.combat_bf_index < 0:
		return ["[INFO] Cannon Barrage: no combat in progress — no targets"]
	if gs.prevent_spell_ability_damage:
		return ["> Damage from spells/abilities prevented"]
	var caster_owner := source.owner_index if source else gs.focus_player_index
	# Enemy = the side opposing the caster among the two combatants.
	var enemy_pi := 1 - caster_owner
	var bf = gs.board.battlefields[gs.combat_bf_index]
	var log_lines: Array[String] = []
	for u in Array(bf.units[enemy_pi]):
		u.add_damage(amount)
		log_lines.append("> Cannon Barrage dealt %d to %s (total: %d/%d)" % [
			amount, u.display_name(), u.damage, u.get_current_might()
		])
	if log_lines.is_empty():
		log_lines.append("> Cannon Barrage: no enemy units in combat")
	return log_lines


func _fight_chosen_units(_source: CardInstance, chosen_enemy: CardInstance, ctx: Dictionary, gs: GameState = null) -> Array:
	var chosen_targets: Array = ctx.get("chosen_targets", [])
	var buffed_friendly: CardInstance = null
	if not chosen_targets.is_empty() and chosen_targets[0] is CardInstance:
		buffed_friendly = chosen_targets[0]
	if buffed_friendly == null:
		return ["[INFO] fight_chosen_units: missing friendly target"]
	if chosen_enemy == null:
		return ["[INFO] fight_chosen_units: missing enemy target"]
	if gs != null and gs.prevent_spell_ability_damage:
		return ["> Damage from spells/abilities prevented"]
	var friendly_might = buffed_friendly.get_current_might()
	var enemy_might = chosen_enemy.get_current_might()
	chosen_enemy.add_damage(friendly_might)
	buffed_friendly.add_damage(enemy_might)
	return [
		"> %s dealt %d to %s" % [buffed_friendly.display_name(), friendly_might, chosen_enemy.display_name()],
		"> %s dealt %d to %s" % [chosen_enemy.display_name(), enemy_might, buffed_friendly.display_name()],
	]


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


func _play_token(params: Dictionary, source: CardInstance, gs: GameState, owner: int) -> Array:
	var token_type: String = params.get("token_type", "recruit_1m")
	var location: String = params.get("location", "base")
	var ps: PlayerState = gs.players[owner]
	var token_def = CardLoader.get_card(token_type)
	if token_def == null:
		return ["> [ERROR] Unknown token type: %s" % token_type]
	var token = ps.create_instance(token_def)
	token.is_exhausted = not params.get("ready", false)
	for kw in params.get("keywords", []):
		token.temp_keywords.append(kw)
	if location == "here" and source != null and source.is_at_battlefield():
		gs.board.add_unit_to_battlefield(token, source.battlefield_index)
		location = gs.board.battlefields[source.battlefield_index].battlefield_id
	else:
		token.location = "base"
		ps.base_permanents.append(token)
	return ["> P%d created a token: %s at %s" % [owner + 1, token.display_name(), location]]


func _gain_points(params: Dictionary, gs: GameState, owner: int) -> Array:
	var amount: int = params.get("amount", 1)
	gs.players[owner].score += amount
	return ["> P%d gained %d point(s). Score: P1=%d, P2=%d" % [
		owner + 1, amount, gs.players[0].score, gs.players[1].score
	]]


func _counter_spell(source: CardInstance, gs: GameState, params: Dictionary = {}) -> Array:
	if gs.chain.is_empty():
		return ["> [ERROR] Nothing on the chain to counter"]
	var item = gs.chain[gs.chain.size() - 1]
	if not _chain_item_matches_counter_limits(item, params):
		return ["> [ERROR] Top of chain costs too much to counter"]
	gs.chain.erase(item)
	var src_name = source.display_name() if source else "Effect"
	return ["> %s countered %s" % [src_name, item.describe()]]


static func _chain_item_matches_counter_limits(item: ChainItem, params: Dictionary) -> bool:
	if params.is_empty():
		return true
	if item == null or item.source_card == null:
		return false
	if item.source_card.definition.card_type != "spell":
		return false
	var max_energy = int(params.get("max_energy", -1))
	var max_power = int(params.get("max_power_total", -1))
	var energy = item.source_card.definition.energy_cost
	var power_total := 0
	for p in item.source_card.definition.power_cost:
		power_total += int(p.get("amount", 0))
	if max_energy >= 0 and energy > max_energy:
		return false
	if max_power >= 0 and power_total > max_power:
		return false
	return true


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
	var valid: Array[CardInstance] = []
	var valid_ids: Array[String] = []
	for card in ps.trash:
		if target_type == "any" or card.definition.card_type == target_type:
			valid.append(card)
			valid_ids.append(card.instance_id)
	if valid.size() > 1 and ctx.get("controller") != null:
		gs.pending_prompt = {
			"player_index": owner,
			"type": "choose_trash_return",
			"valid_choices": valid_ids,
			"prompt": "[PROMPT] Choose a %s from trash — use: choose <%s>" % [
				target_type, "|".join(valid_ids)
			],
		}
		return [gs.pending_prompt["prompt"]]
	if valid.size() == 1:
		var card = valid[0]
		ps.move_to_hand(card)
		return ["> P%d returned %s from trash to hand" % [owner + 1, card.display_name()]]
	return ["> P%d has no %s in trash to return" % [owner + 1, target_type]]


func _other_friendly_enter_ready(source: CardInstance, gs: GameState) -> Array:
	# This passive is applied at placement time by GameController._place_unit.
	return []


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
	var controller: GameController = ctx.get("controller")
	if controller != null:
		controller.play_unit_from_effect(source, owner)
		return ["> %s played itself from discard" % source.display_name()]
	var ps = gs.players[owner]
	ps.trash.erase(source)
	source.location = "base"
	source.is_exhausted = true
	ps.cards_played_this_turn += 1
	source.played_this_turn = true
	ps.base_permanents.append(source)
	return ["> %s played itself from discard" % source.display_name()]


func _death_replacement_recall(target: CardInstance, gs: GameState) -> Array:
	if target == null:
		return ["[INFO] death_replacement_recall: no target provided"]
	gs.death_replacement_recalls[target.instance_id] = {
		"target": target,
		"turn_number": gs.turn_number,
	}
	return ["> %s is protected from its next death this turn" % target.display_name()]


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
	if gs.prevent_spell_ability_damage:
		return ["> Damage from spells/abilities prevented"]
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
