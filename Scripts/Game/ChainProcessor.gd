class_name ChainProcessor

# Manages the Chain (stack) per §8 of the implementation rules.
# FEPR: Finalize → Execute → Pass priority → Resolve

static func on_card_added_to_chain(gs: GameState) -> Array:
	# When a card is placed on the chain, state becomes Closed
	var log_lines: Array[String] = []
	var prev_open = gs.current_state == TurnStateMachine.State.NEUTRAL_OPEN
	if prev_open:
		gs.current_state = TurnStateMachine.State.NEUTRAL_CLOSED
	elif gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN:
		gs.current_state = TurnStateMachine.State.SHOWDOWN_CLOSED
	gs.passes_in_sequence = 0
	# Priority passes to opponent to allow reactions
	gs.priority_player_index = 1 - gs.priority_player_index
	if gs.current_state == TurnStateMachine.State.NEUTRAL_CLOSED or \
	   gs.current_state == TurnStateMachine.State.SHOWDOWN_CLOSED:
		log_lines.append("[PROMPT] P%d: play Reaction or 'pass' to let it resolve" % (gs.priority_player_index + 1))
	return log_lines


static func resolve_chain_item(item: ChainItem, gs: GameState, ability_resolver: AbilityResolver) -> Array:
	var log_lines: Array[String] = []
	log_lines.append("> Resolving: %s" % item.describe())
	var resolve_lines = _execute_chain_item(item, gs, ability_resolver)
	log_lines.append_array(resolve_lines)
	if gs.chain.is_empty():
		log_lines.append_array(_return_to_open(gs))
	else:
		gs.passes_in_sequence = 0
		gs.priority_player_index = 1 - item.owner_index
		log_lines.append("[PROMPT] P%d: play Reaction or 'pass'" % (gs.priority_player_index + 1))
	return log_lines


static func handle_pass(gs: GameState, ability_resolver: AbilityResolver) -> Array:
	var log_lines: Array[String] = []
	gs.passes_in_sequence += 1

	if gs.passes_in_sequence < gs.players.size():
		# Not everyone passed yet — switch priority
		gs.priority_player_index = 1 - gs.priority_player_index
		log_lines.append("[PROMPT] P%d: play Reaction or 'pass'" % (gs.priority_player_index + 1))
		return log_lines

	# All players passed → resolve top of chain
	var item = gs.pop_chain()
	if item == null:
		log_lines.append_array(_return_to_open(gs))
		return log_lines

	log_lines.append("> Resolving: %s" % item.describe())
	gs.passes_in_sequence = 0

	# Check if item needs a target before resolving
	if item.needs_target:
		gs.pending_prompt = {
			"player_index": item.owner_index,
			"type": "choose_target",
			"chain_item": item,
			"prompt": item.target_prompt,
			"valid_choices": item.valid_targets if not item.valid_targets.is_empty() else []
		}
		log_lines.append("[PROMPT] %s" % item.target_prompt)
		return log_lines

	# Resolve effects
	var resolve_lines = _execute_chain_item(item, gs, ability_resolver)
	log_lines.append_array(resolve_lines)

	# If chain is empty, return to open state
	if gs.chain.is_empty():
		log_lines.append_array(_return_to_open(gs))
	else:
		# More items on chain — next player gets priority
		gs.passes_in_sequence = 0
		gs.priority_player_index = 1 - item.owner_index
		log_lines.append("[PROMPT] P%d: play Reaction or 'pass'" % (gs.priority_player_index + 1))

	return log_lines


static func _execute_chain_item(item: ChainItem, gs: GameState, ability_resolver: AbilityResolver) -> Array:
	var log_lines: Array[String] = []

	if item.item_type == ChainItem.ItemType.CARD:
		var card = item.source_card
		if card == null:
			return log_lines
		# Execute all triggered (resolution-timing) abilities
		for ab in card.definition.abilities:
			if ab.get("timing", "") == "resolution":
				var target = item.targets[0] if not item.targets.is_empty() else null
				var owner_pi = card.owner_index
				var cost = ab.get("cost", {})
				if not cost.is_empty():
					var computed = CostCalculator.compute_ability_cost(cost, card, target, gs)
					if CostCalculator.can_afford(owner_pi, computed, gs):
						CostCalculator.pay_cost(owner_pi, computed, card, gs)
				var ctx = {"controller": null, "player_index": owner_pi}
				var ab_lines = ability_resolver.resolve_ability(ab, card, target, gs, ctx)
				log_lines.append_array(ab_lines)
		# If spell → move to trash
		if card.definition.card_type == "spell":
			gs.players[card.owner_index].move_to_trash(card)
		# If unit → already placed on board during play, nothing to do here
		# If gear → already placed during play

	elif item.item_type == ChainItem.ItemType.ABILITY:
		var target = item.targets[0] if not item.targets.is_empty() else null
		var ctx = {"player_index": item.source_card.owner_index if item.source_card else 0}
		var ab_lines = ability_resolver.resolve_ability(item.ability_def, item.source_card, target, gs, ctx)
		log_lines.append_array(ab_lines)

	return log_lines


static func _return_to_open(gs: GameState) -> Array:
	var log_lines: Array[String] = []
	if gs.is_showdown_state():
		gs.current_state = TurnStateMachine.State.SHOWDOWN_OPEN
		gs.priority_player_index = gs.turn_player_index
	else:
		gs.current_state = TurnStateMachine.State.NEUTRAL_OPEN
		gs.priority_player_index = gs.turn_player_index
	gs.passes_in_sequence = 0
	return log_lines
