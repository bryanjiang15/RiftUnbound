class_name GameController
extends Node

signal board_updated
signal game_log_message(text: String)

const P1_DECK = "res://Data/Decks/starter-deck-p1.json"
const P2_DECK = "res://Data/Decks/starter-deck-p2.json"

var gs: GameState = GameState.new()
var ability_resolver: AbilityResolver = AbilityResolver.new()

var _ai_player_index: int = 1  # which player is AI (-1 = human vs human)


func _ready() -> void:
	start_game()


func start_game() -> void:
	gs = GameState.new()
	gs.players.clear()

	var p1 = DeckLoader.build_player_state(P1_DECK, 0)
	var p2 = DeckLoader.build_player_state(P2_DECK, 1)
	if p1 == null or p2 == null:
		_log("[ERROR] Failed to load decks. Check Data/Decks/ paths.")
		return
	gs.players.append(p1)
	gs.players.append(p2)

	# Select battlefields (1 random from each player's list)
	var p1_bf = p1.deck_battlefields[randi() % p1.deck_battlefields.size()]
	var p2_bf = p2.deck_battlefields[randi() % p2.deck_battlefields.size()]
	if p1_bf == p2_bf and p1.deck_battlefields.size() > 1:
		for bf in p1.deck_battlefields:
			if bf != p2_bf:
				p1_bf = bf
				break
	gs.board.setup(p1_bf, p2_bf)

	# Randomly choose who goes first
	gs.turn_player_index = randi() % 2
	gs.priority_player_index = gs.turn_player_index

	# P2 (second player) gets +1 rune on first channel
	var second_player = 1 - gs.turn_player_index
	gs.first_channel_done[gs.turn_player_index] = false
	gs.first_channel_done[second_player] = false

	_log("> Riftbound 1v1 — %s vs %s" % [p1.player_name, p2.player_name])
	_log("> Battlefields: %s and %s" % [
		gs.board.battlefields[0].display_name,
		gs.board.battlefields[1].display_name
	])
	_log("> P%d goes first" % (gs.turn_player_index + 1))

	# Deal 4 cards each
	for ps in gs.players:
		for _i in range(4):
			var drawn = ps.draw_card()
			if drawn:
				_log("> [P%d] Drew %s" % [ps.player_index + 1, drawn.display_name()])

	# Enter mulligan phase
	gs.mulligan_phase = true
	gs.mulligan_done = [false, false]
	_log("> Mulligan: each player may set aside up to 2 cards.")
	_log("[PROMPT] P1 goes first — type: p1 mulligan keep  |  p1 mulligan <id> [id]")
	_log("[PROMPT] P2 goes after  — type: p2 mulligan keep  |  p2 mulligan <id> [id]")

	board_updated.emit()


# ─── Public entry point ──────────────────────────────────────────────────────

func submit_command(player_index: int, raw: String) -> void:
	if gs.game_over:
		_log("[ERROR] Game is over. Type 'new game' to start again.")
		return

	var text = raw.strip_edges().to_lower()
	if text.is_empty():
		return

	_log("[P%d] > %s" % [player_index + 1, raw.strip_edges()])

	# Route to appropriate handler
	var tokens = text.split(" ", false)
	if tokens.is_empty():
		return

	var verb = tokens[0]
	var args = tokens.slice(1)

	match verb:
		"mulligan":
			_cmd_mulligan(player_index, args)
		"pass":
			_cmd_pass(player_index)
		"end":
			if args.size() > 0 and args[0] == "turn":
				_cmd_end_turn(player_index)
			else:
				_log("[ERROR] Did you mean 'end turn'?")
		"tap":
			_cmd_tap_rune(player_index, args)
		"recycle":
			_cmd_recycle_rune(player_index, args)
		"play":
			_cmd_play(player_index, args)
		"move":
			_cmd_move(player_index, args)
		"use":
			_cmd_use(player_index, args)
		"react":
			_cmd_react(player_index, args)
		"assign":
			_cmd_assign(player_index, args)
		"choose":
			_cmd_choose(player_index, args)
		"hand":
			_cmd_hand(player_index)
		"board":
			_cmd_board()
		"card":
			_cmd_card(player_index, args)
		"chain":
			_cmd_chain()
		"score":
			_cmd_score()
		"pool":
			_cmd_pool(player_index)
		"zones":
			_cmd_zones()
		"help":
			_cmd_help(player_index)
		"new":
			if args.size() > 0 and args[0] == "game":
				start_game()
		_:
			_log("[ERROR] Unknown command '%s'. Type 'help' for available commands." % verb)

	board_updated.emit()
	_maybe_trigger_ai()


# ─── Mulligan ────────────────────────────────────────────────────────────────

var _mulligan_set_aside: Array = [[], []]

func _cmd_mulligan(player_index: int, args: Array) -> void:
	if not gs.mulligan_phase:
		_log("[ERROR] Mulligan phase is over.")
		return
	if gs.mulligan_done[player_index]:
		_log("[ERROR] P%d already completed mulligan." % (player_index + 1))
		return

	var ps: PlayerState = gs.players[player_index]

	if args.size() > 0 and args[0] == "keep":
		gs.mulligan_done[player_index] = true
		_log("> P%d kept their hand" % (player_index + 1))
	else:
		var to_set: Array = []
		for id_arg in args:
			var card = ps.get_hand_instance(id_arg)
			if card == null:
				_log("[ERROR] P%d: '%s' not found in hand." % [player_index + 1, id_arg])
				return
			to_set.append(card)
		if to_set.size() > 2:
			_log("[ERROR] Mulligan: set aside at most 2 cards.")
			return
		_mulligan_set_aside[player_index] = to_set
		for card in to_set:
			ps.hand.erase(card)
			var drawn = ps.draw_card()
			if drawn:
				_log("> P%d drew %s" % [player_index + 1, drawn.display_name()])
		# Recycle set-aside cards to bottom of deck
		for card in to_set:
			card.location = "deck"
			ps.deck.append(card)
		gs.mulligan_done[player_index] = true
		_log("> P%d mulliganed %d card(s)" % [player_index + 1, to_set.size()])

	# Check if both players done
	if gs.mulligan_done[0] and gs.mulligan_done[1]:
		gs.mulligan_phase = false
		_log("> Mulligan complete. Beginning Turn 1 for P%d." % (gs.turn_player_index + 1))
		_execute_start_of_turn()
	elif not gs.mulligan_done[0]:
		_log("[PROMPT] Waiting for P1 — type: p1 mulligan keep  |  p1 mulligan <id> [id]")
		board_updated.emit()
	elif not gs.mulligan_done[1]:
		_log("[PROMPT] Waiting for P2 — type: p2 mulligan keep  |  p2 mulligan <id> [id]")
		board_updated.emit()


# ─── Turn phases ─────────────────────────────────────────────────────────────

func _execute_start_of_turn() -> void:
	var turn_pi = gs.turn_player_index
	_log("> === Turn %d — P%d's turn ===" % [gs.turn_number, turn_pi + 1])

	# Awaken Phase
	gs.current_phase = TurnStateMachine.Phase.AWAKEN
	_log("> Awaken Phase")
	var ps: PlayerState = gs.players[turn_pi]
	for perm in ps.base_permanents:
		perm.ready()
	for bf in gs.board.battlefields:
		for u in bf.units[turn_pi]:
			u.ready()
	for rune in ps.channeled_runes:
		rune.ready()
	if ps.champion_zone:
		ps.champion_zone.ready()

	# Beginning Phase
	gs.current_phase = TurnStateMachine.Phase.BEGINNING
	_log("> Beginning Phase")
	# Scoring Step: Hold — gain 1 pt per controlled battlefield
	for i in range(gs.board.battlefields.size()):
		var bf = gs.board.battlefields[i]
		if bf.controller_index == turn_pi:
			if not i in ps.battlefields_scored_this_turn:
				ps.battlefields_scored_this_turn.append(i)
				ps.score += 1
				_log("> P%d scores 1 point (Hold: %s). Score: P1=%d, P2=%d" % [
					turn_pi + 1, bf.display_name, gs.players[0].score, gs.players[1].score
				])

	# Channel Phase
	gs.current_phase = TurnStateMachine.Phase.CHANNEL
	_log("> Channel Phase")
	var runes_to_channel = 2
	if not gs.first_channel_done[turn_pi]:
		gs.first_channel_done[turn_pi] = true
		if turn_pi != gs.turn_player_index:  # second player bonus is on their first turn
			# Second player who goes second gets +1 rune on THEIR first turn
			pass
	# Second player bonus: on their first channel, get +1
	var second_pi = 1 - _determine_first_player()
	if turn_pi == second_pi and gs.turn_number <= 2 and ps.channeled_runes.is_empty():
		runes_to_channel = 3
		_log("> P%d (going second) channels 3 Runes this first turn" % (turn_pi + 1))

	for _i in range(runes_to_channel):
		var rune = ps.channel_rune()
		if rune:
			var domain_abbr = CardDefinition._domain_abbr(rune.definition.domain[0]) if rune.definition.domain.size() > 0 else "?"
			_log("> P%d channeled a %s Rune" % [turn_pi + 1, domain_abbr])

	# Draw Phase
	gs.current_phase = TurnStateMachine.Phase.DRAW
	var drawn = ps.draw_card()
	if drawn:
		_log("> P%d drew %s" % [turn_pi + 1, drawn.display_name()])
	else:
		_log("[INFO] P%d's deck is empty!" % (turn_pi + 1))

	# Empty rune pools
	gs.players[0].rune_pool.empty()
	gs.players[1].rune_pool.empty()

	# Main Phase
	gs.current_phase = TurnStateMachine.Phase.MAIN
	gs.current_state = TurnStateMachine.State.NEUTRAL_OPEN
	gs.priority_player_index = turn_pi
	_log("> Main Phase — P%d has Priority" % (turn_pi + 1))
	_log("[PROMPT] P%d: tap runes, play cards, move units, or 'end turn'" % (turn_pi + 1))


var _first_player_cache: int = -1

func _determine_first_player() -> int:
	if _first_player_cache < 0:
		_first_player_cache = gs.turn_player_index
	return _first_player_cache


func _cmd_end_turn(player_index: int) -> void:
	if gs.current_phase != TurnStateMachine.Phase.MAIN:
		_log("[ERROR] Can only end turn during Main Phase.")
		return
	if player_index != gs.turn_player_index:
		_log("[ERROR] Not your turn.")
		return
	if gs.current_state != TurnStateMachine.State.NEUTRAL_OPEN:
		_log("[ERROR] Cannot end turn while a Chain or Showdown is active.")
		return
	_execute_end_of_turn()


func _execute_end_of_turn() -> void:
	var turn_pi = gs.turn_player_index
	gs.current_phase = TurnStateMachine.Phase.ENDING
	_log("> Ending Phase")

	# Expiration Step: Heal all units; expire turn effects; empty rune pool
	CleanupProcessor.heal_all_units(gs)
	CleanupProcessor.expire_turn_effects(gs)
	gs.players[turn_pi].rune_pool.empty()
	gs.players[1 - turn_pi].rune_pool.empty()

	# Clear stun from turn player's units (stun clears at Ending Step)
	for ps in gs.players:
		for u in ps.get_units_at_base():
			u.clear_stun()
		for u in gs.board.get_all_units_on_board(ps.player_index):
			u.clear_stun()

	_log("> P%d ended their turn." % (turn_pi + 1))

	# Pass to next player
	gs.turn_player_index = 1 - turn_pi
	gs.turn_number += 1
	gs.priority_player_index = gs.turn_player_index
	gs.focus_player_index = -1
	gs.passes_in_sequence = 0
	gs.attacker_player_index = -1
	gs.current_state = TurnStateMachine.State.NEUTRAL_OPEN

	_execute_start_of_turn()


# ─── Pass / Priority ─────────────────────────────────────────────────────────

func _cmd_pass(player_index: int) -> void:
	if gs.mulligan_phase:
		_log("[ERROR] Use 'mulligan keep' during mulligan phase.")
		return

	# If in showdown/combat
	if gs.current_state == TurnStateMachine.State.SHOWDOWN_OPEN or \
	   gs.current_state == TurnStateMachine.State.SHOWDOWN_CLOSED:
		if player_index != gs.focus_player_index:
			_log("[ERROR] You do not have Focus.")
			return
		var lines: Array
		if gs.combat_bf_index >= 0:
			lines = CombatProcessor.handle_pass(gs)
		else:
			lines = ShowdownProcessor.handle_pass(gs)
		for l in lines:
			_log(l)
		# Run cleanup after showdown resolves
		_run_cleanup()
		return

	# If chain is active
	if not gs.chain.is_empty():
		if not gs.can_player_act(player_index):
			_log("[ERROR] Not your turn to act.")
			return
		var lines = ChainProcessor.handle_pass(gs, ability_resolver)
		for l in lines:
			_log(l)
		_run_cleanup()
		return

	# Neutral Open: pass ends turn (same as end turn)
	if gs.current_phase == TurnStateMachine.Phase.MAIN:
		if player_index != gs.turn_player_index:
			_log("[ERROR] Not your turn.")
			return
		_execute_end_of_turn()
	else:
		_log("[ERROR] Nothing to pass right now.")


# ─── Resource commands ────────────────────────────────────────────────────────

func _cmd_tap_rune(player_index: int, args: Array) -> void:
	if not _check_can_act(player_index):
		return
	if args.is_empty():
		_log("[ERROR] Usage: tap rune-<n>")
		return
	var rune_id = args[0]
	if not rune_id.begins_with("rune-"):
		_log("[ERROR] Rune ID format: rune-0, rune-1, etc.")
		return
	var idx = int(rune_id.trim_prefix("rune-"))
	var ps: PlayerState = gs.players[player_index]
	var rune = ps.get_rune_by_index(idx)
	if rune == null:
		_log("[ERROR] No rune at index %d" % idx)
		return
	if rune.is_exhausted:
		_log("[ERROR] %s is already exhausted." % rune_id)
		return
	# Execute the tap ability (add_energy)
	for ab in rune.definition.abilities:
		if ab.get("effect_type", "") == "add_energy":
			var cost = ab.get("cost", {})
			if cost.get("exhaust", false):
				rune.exhaust()
			var lines = ability_resolver.resolve_ability(ab, rune, null, gs)
			for l in lines:
				_log(l)
			return
	_log("[ERROR] Rune has no tap ability.")


func _cmd_recycle_rune(player_index: int, args: Array) -> void:
	if not _check_can_act(player_index):
		return
	if args.is_empty():
		_log("[ERROR] Usage: recycle rune-<n>")
		return
	var rune_id = args[0]
	if not rune_id.begins_with("rune-"):
		_log("[ERROR] Rune ID format: rune-0, rune-1, etc.")
		return
	var idx = int(rune_id.trim_prefix("rune-"))
	var ps: PlayerState = gs.players[player_index]
	var rune = ps.get_rune_by_index(idx)
	if rune == null:
		_log("[ERROR] No rune at index %d" % idx)
		return
	for ab in rune.definition.abilities:
		if ab.get("effect_type", "") == "add_power":
			CostCalculator.pay_cost(player_index, ab.get("cost", {}), rune, gs)
			var lines = ability_resolver.resolve_ability(ab, rune, null, gs)
			for l in lines:
				_log(l)
			_log("> Rune recycled to bottom of Rune Deck")
			return
	_log("[ERROR] Rune has no recycle ability.")


# ─── Play card ────────────────────────────────────────────────────────────────

func _cmd_play(player_index: int, args: Array) -> void:
	if not _check_can_act(player_index):
		return
	if gs.current_phase != TurnStateMachine.Phase.MAIN:
		_log("[ERROR] Can only play cards during Main Phase.")
		return

	# Parse: play <id> [to <location>] [target <id>] [from champion|hidden] [accelerate]
	var card_id = ""
	var destination = ""
	var target_id = ""
	var from_zone = "hand"
	var use_accelerate = false

	var i = 0
	while i < args.size():
		var a = args[i]
		if a == "to" and i + 1 < args.size():
			destination = args[i + 1]
			i += 2
		elif a == "target" and i + 1 < args.size():
			target_id = args[i + 1]
			i += 2
		elif a == "from" and i + 1 < args.size():
			from_zone = args[i + 1]
			i += 2
		elif a == "accelerate":
			use_accelerate = true
			i += 1
		elif card_id.is_empty():
			card_id = a
			i += 1
		else:
			i += 1

	if card_id.is_empty():
		_log("[ERROR] Usage: play <card-id> [to <location>] [target <id>]")
		return

	var ps: PlayerState = gs.players[player_index]
	var card: CardInstance = null

	if from_zone == "champion":
		if ps.champion_zone and ps.champion_zone.instance_id == card_id:
			card = ps.champion_zone
		else:
			_log("[ERROR] '%s' not in Champion Zone." % card_id)
			return
	elif from_zone == "hidden":
		# Find face-down card at a controlled battlefield
		for bf in gs.board.battlefields:
			if bf.controller_index == player_index and bf.facedown_card and \
			   bf.facedown_card.instance_id == card_id:
				card = bf.facedown_card
				bf.facedown_card = null
				break
		if card == null:
			_log("[ERROR] No hidden card '%s' found at controlled Battlefield." % card_id)
			return
	else:
		card = ps.get_hand_instance(card_id)
		if card == null:
			_log("[ERROR] '%s' not found in hand." % card_id)
			return

	# Timing check
	if not TurnStateMachine.can_play_card(card, gs.current_state, player_index, gs):
		_log("[ERROR] Cannot play %s in current state (%s)." % [card.definition.name, gs.get_state_name()])
		return

	# Compute cost
	var cost = CostCalculator.compute_play_cost(card, player_index, gs, use_accelerate)
	if not CostCalculator.can_afford(player_index, cost, gs):
		_log("[ERROR] Cannot play %s: insufficient resources (need %s, pool: %s)" % [
			card.definition.name, CostCalculator.cost_to_string(cost),
			ps.rune_pool.describe()
		])
		return

	# Pay cost
	CostCalculator.pay_cost(player_index, cost, null, gs)
	ps.cards_played_this_turn += 1
	card.played_this_turn = true

	# Remove from source zone
	if from_zone == "hand":
		ps.hand.erase(card)
	elif from_zone == "champion":
		ps.champion_zone = null

	_log("> [P%d] Played %s" % [player_index + 1, card.definition.name])

	match card.definition.card_type:
		"unit":
			_place_unit(player_index, card, destination, use_accelerate)
		"gear":
			_place_gear(player_index, card, destination)
		"spell":
			_play_spell(player_index, card, target_id, destination)

	# Vision keyword: look at top of deck
	if card.has_keyword("vision") and card.definition.card_type == "unit":
		_handle_vision(player_index, card)

	_run_cleanup()


func _place_unit(player_index: int, card: CardInstance, destination: String, use_accelerate: bool) -> void:
	var ps: PlayerState = gs.players[player_index]

	# Default: send to base
	if destination.is_empty() or destination == "base":
		card.location = "base"
		card.is_exhausted = not use_accelerate  # enters exhausted unless Accelerate
		ps.base_permanents.append(card)
		_log("> %s placed at P%d base (%s)" % [
			card.definition.name, player_index + 1,
			"ready" if use_accelerate else "exhausted"
		])
	elif destination.begins_with("battlefield"):
		var bf_idx = gs.board.get_battlefield_index(destination)
		if bf_idx < 0:
			_log("[ERROR] Unknown battlefield '%s'" % destination)
			ps.base_permanents.append(card)
			card.location = "base"
			return
		card.is_exhausted = not use_accelerate
		gs.board.add_unit_to_battlefield(card, bf_idx)
		_log("> %s placed at %s (%s)" % [
			card.definition.name, destination, "ready" if use_accelerate else "exhausted"
		])
		# Mark contested if opponent controls or has units
		var bf = gs.board.battlefields[bf_idx]
		if bf.controller_index >= 0 and bf.controller_index != player_index:
			bf.is_contested = true
			gs.attacker_player_index = player_index
		elif not bf.units[1 - player_index].is_empty():
			bf.is_contested = true
			gs.attacker_player_index = player_index


func _place_gear(player_index: int, card: CardInstance, target_id: String) -> void:
	var ps: PlayerState = gs.players[player_index]
	card.location = "base"
	card.is_exhausted = false
	ps.base_permanents.append(card)
	_log("> %s placed at P%d base" % [card.definition.name, player_index + 1])


func _play_spell(player_index: int, card: CardInstance, target_id: String, destination: String) -> void:
	var ps: PlayerState = gs.players[player_index]
	card.owner_index = player_index

	var target: CardInstance = null
	if not target_id.is_empty():
		target = gs.find_instance_anywhere(target_id)
		if target == null:
			_log("[ERROR] Target '%s' not found." % target_id)
			ps.move_to_trash(card)
			return

	# Push to chain
	var item = ChainItem.from_card(card)
	item.targets = [target] if target != null else []

	# For spells needing a target but none provided, check if they need one
	var needs_target_selection = false
	for ab in card.definition.abilities:
		if ab.get("timing", "") == "resolution":
			var target_param = ab.get("effect_params", {}).get("targeting", "")
			if target_param == "choose_one" and target == null:
				needs_target_selection = true
				item.needs_target = true
				item.target_prompt = _build_target_prompt(card, ab, player_index, gs)
				item.target_filter = ab.get("effect_params", {}).get("target", "")
				break

	gs.push_to_chain(item)
	_log("> %s added to Chain" % card.definition.name)

	var chain_lines = ChainProcessor.on_card_added_to_chain(gs)
	for l in chain_lines:
		_log(l)


func _handle_vision(player_index: int, card: CardInstance) -> void:
	# Trigger vision ability on play
	for ab in card.definition.abilities:
		if ab.get("timing", "") == "play" and ab.get("effect_type", "") == "predict":
			var lines = ability_resolver.resolve_ability(ab, card, null, gs)
			for l in lines:
				_log(l)


# ─── Move ─────────────────────────────────────────────────────────────────────

func _cmd_move(player_index: int, args: Array) -> void:
	if not _check_can_act(player_index):
		return
	if gs.current_phase != TurnStateMachine.Phase.MAIN:
		_log("[ERROR] Can only move units during Main Phase.")
		return
	if gs.current_state != TurnStateMachine.State.NEUTRAL_OPEN:
		_log("[ERROR] Cannot move during Chain or Showdown.")
		return

	# move <id> [id...] to <destination>
	var to_idx = -1
	for i in range(args.size()):
		if args[i] == "to":
			to_idx = i
			break
	if to_idx < 0 or to_idx >= args.size() - 1:
		_log("[ERROR] Usage: move <unit-id> [id...] to <base|battlefield-a|battlefield-b>")
		return

	var unit_ids = args.slice(0, to_idx)
	var destination = args[to_idx + 1]

	var ps: PlayerState = gs.players[player_index]
	var units_to_move: Array = []

	for uid in unit_ids:
		var unit = _find_player_unit(player_index, uid)
		if unit == null:
			_log("[ERROR] Unit '%s' not found or not yours." % uid)
			return
		if unit.is_exhausted:
			_log("[ERROR] %s is exhausted and cannot move." % uid)
			return
		units_to_move.append(unit)

	if units_to_move.is_empty():
		_log("[ERROR] No valid units specified.")
		return

	# Validate destination
	var dest_bf_idx = -1
	if destination != "base":
		dest_bf_idx = gs.board.get_battlefield_index(destination)
		if dest_bf_idx < 0:
			_log("[ERROR] Unknown location '%s'. Use: base, battlefield-a, battlefield-b" % destination)
			return

	for unit in units_to_move:
		# Ganking check: Battlefield → Battlefield
		var is_at_bf = unit.is_at_battlefield()
		if is_at_bf and dest_bf_idx >= 0:
			if not unit.has_keyword("ganking"):
				_log("[ERROR] %s cannot Gank (no Ganking keyword)." % unit.instance_id)
				return

		# Execute move
		unit.exhaust()
		if unit.is_at_battlefield():
			gs.board.remove_unit_from_battlefield(unit)
		else:
			ps.base_permanents.erase(unit)

		if destination == "base":
			unit.location = "base"
			ps.base_permanents.append(unit)
			_log("> [P%d] %s moved to base" % [player_index + 1, unit.display_name()])
		else:
			gs.board.add_unit_to_battlefield(unit, dest_bf_idx)
			_log("> [P%d] %s moved to %s" % [player_index + 1, unit.display_name(), destination])
			# Check if this triggers contested
			var bf = gs.board.battlefields[dest_bf_idx]
			if bf.controller_index >= 0 and bf.controller_index != player_index:
				bf.is_contested = true
				gs.attacker_player_index = player_index
				_log("> %s is now Contested" % bf.display_name)
			elif not bf.units[1 - player_index].is_empty():
				bf.is_contested = true
				gs.attacker_player_index = player_index
				_log("> %s is now Contested" % bf.display_name)

	_run_cleanup()


func _find_player_unit(player_index: int, inst_id: String) -> CardInstance:
	var ps: PlayerState = gs.players[player_index]
	for u in ps.get_units_at_base():
		if u.instance_id == inst_id:
			return u
	var u = gs.board.find_unit_on_board(inst_id)
	if u != null and u.owner_index == player_index:
		return u
	return null


# ─── Use ability ─────────────────────────────────────────────────────────────

func _cmd_use(player_index: int, args: Array) -> void:
	if not _check_can_act(player_index):
		return
	if args.is_empty():
		_log("[ERROR] Usage: use <card-id> [target <target-id>]")
		return

	var card_id = args[0]
	var target_id = ""
	if args.size() >= 3 and args[1] == "target":
		target_id = args[2]

	var card = _find_player_permanent(player_index, card_id)
	if card == null:
		_log("[ERROR] '%s' not found or not yours." % card_id)
		return

	# Find an activated ability
	var ab: Dictionary = {}
	for a in card.definition.abilities:
		if a.get("ability_type", "") == "activated" and a.get("effect_type", "") != "attach":
			ab = a
			break
	if ab.is_empty():
		_log("[ERROR] %s has no activated ability." % card.definition.name)
		return

	if not TurnStateMachine.can_activate_ability(ab, gs.current_state, player_index, gs):
		_log("[ERROR] Cannot activate that ability in current state.")
		return

	var target: CardInstance = null
	if not target_id.is_empty():
		target = gs.find_instance_anywhere(target_id)

	var cost = CostCalculator.compute_ability_cost(ab, card, target, gs)
	if not CostCalculator.can_afford(player_index, cost, gs):
		_log("[ERROR] Cannot afford ability cost: %s" % CostCalculator.cost_to_string(cost))
		return

	CostCalculator.pay_cost(player_index, cost, card, gs)

	var item = ChainItem.from_ability(card, ab, 0)
	if target:
		item.targets.append(target)
	gs.push_to_chain(item)
	_log("> [P%d] Activated ability on %s" % [player_index + 1, card.display_name()])
	var chain_lines = ChainProcessor.on_card_added_to_chain(gs)
	for l in chain_lines:
		_log(l)
	_run_cleanup()


# ─── React ────────────────────────────────────────────────────────────────────

func _cmd_react(player_index: int, args: Array) -> void:
	if args.is_empty():
		_log("[ERROR] Usage: react <card-id> [target <id>]")
		return
	if gs.current_state != TurnStateMachine.State.NEUTRAL_CLOSED and \
	   gs.current_state != TurnStateMachine.State.SHOWDOWN_CLOSED:
		_log("[ERROR] Can only react during Closed states.")
		return

	var card_id = args[0]
	var target_id = ""
	if args.size() >= 3 and args[1] == "target":
		target_id = args[2]

	var ps: PlayerState = gs.players[player_index]
	var card = ps.get_hand_instance(card_id)
	if card == null:
		_log("[ERROR] '%s' not in hand." % card_id)
		return
	if not card.definition.is_reaction:
		_log("[ERROR] %s is not a Reaction card." % card.definition.name)
		return

	var cost = CostCalculator.compute_play_cost(card, player_index, gs)
	if not CostCalculator.can_afford(player_index, cost, gs):
		_log("[ERROR] Cannot afford %s (need %s, pool: %s)" % [
			card.definition.name, CostCalculator.cost_to_string(cost),
			ps.rune_pool.describe()
		])
		return

	CostCalculator.pay_cost(player_index, cost, null, gs)
	ps.hand.erase(card)
	ps.cards_played_this_turn += 1

	var target: CardInstance = null
	if not target_id.is_empty():
		target = gs.find_instance_anywhere(target_id)

	var item = ChainItem.from_card(card)
	if target:
		item.targets.append(target)
	gs.push_to_chain(item)
	_log("> [P%d] Reacted with %s" % [player_index + 1, card.definition.name])
	gs.passes_in_sequence = 0
	gs.priority_player_index = 1 - player_index
	_log("[PROMPT] P%d: play Reaction or 'pass'" % (gs.priority_player_index + 1))
	_run_cleanup()


# ─── Assign damage ────────────────────────────────────────────────────────────

func _cmd_assign(player_index: int, args: Array) -> void:
	_log("[INFO] Manual damage assignment not yet required — combat damage is auto-assigned.")


# ─── Choose ───────────────────────────────────────────────────────────────────

func _cmd_choose(player_index: int, args: Array) -> void:
	if gs.pending_prompt.is_empty():
		_log("[ERROR] No pending choice.")
		return
	if gs.pending_prompt.get("player_index", -1) != player_index:
		_log("[ERROR] Not your choice to make.")
		return

	var choice = args[0] if not args.is_empty() else "none"
	var prompt_type = gs.pending_prompt.get("type", "")

	if choice == "none":
		_log("> P%d chose none" % (player_index + 1))
		gs.pending_prompt.clear()
		_run_cleanup()
		return

	if prompt_type == "choose_target":
		var item: ChainItem = gs.pending_prompt.get("chain_item")
		if item == null:
			gs.pending_prompt.clear()
			return
		var target = gs.find_instance_anywhere(choice)
		if target == null:
			_log("[ERROR] Target '%s' not found." % choice)
			return
		item.targets = [target]
		item.needs_target = false
		gs.pending_prompt.clear()
		_log("> P%d chose %s as target" % [player_index + 1, target.display_name()])
		# Execute the chain item now
		var lines = ChainProcessor.handle_pass(gs, ability_resolver)
		for l in lines:
			_log(l)
		_run_cleanup()
	else:
		_log("[ERROR] Unknown prompt type: %s" % prompt_type)


# ─── Cleanup helper ─────────────────────────────────────────────────────────

func _run_cleanup() -> void:
	var lines = CleanupProcessor.run(gs, ability_resolver)
	for l in lines:
		_log(l)
	if gs.game_over:
		_log("> Type 'new game' to play again.")


# ─── Info commands ────────────────────────────────────────────────────────────

func _cmd_hand(player_index: int) -> void:
	var ps: PlayerState = gs.players[player_index]
	_log("[INFO] P%d hand (%d cards):\n%s" % [
		player_index + 1, ps.hand.size(), ps.hand_description()
	])


func _cmd_board() -> void:
	_log(gs.board_description())


func _cmd_card(player_index: int, args: Array) -> void:
	if args.is_empty():
		_log("[ERROR] Usage: card <card-id>")
		return
	var card_id = args[0]
	var def = CardLoader.get_card(card_id)
	if def == null:
		_log("[ERROR] Card '%s' not found in database." % card_id)
		return
	var lines: Array[String] = []
	lines.append("[INFO] %s (%s)" % [def.name, def.card_type.to_upper()])
	lines.append("  Cost: %s" % def.cost_string())
	if def.card_type == "unit":
		lines.append("  Might: %d" % def.might)
	if not def.keywords.is_empty():
		var kws: Array[String] = []
		for kw in def.keywords:
			var kw_str = kw.get("id", "")
			if kw.has("value"):
				kw_str += " %d" % kw.get("value")
			kws.append(kw_str.capitalize())
		lines.append("  Keywords: %s" % ", ".join(kws))
	if not def.abilities.is_empty():
		lines.append("  Abilities:")
		for ab in def.abilities:
			lines.append("    [%s] %s → %s" % [
				ab.get("ability_type", "?"),
				ab.get("ability_id", "?"),
				ab.get("effect_type", "?")
			])
	if not def.flavor_text.is_empty():
		lines.append("  \"%s\"" % def.flavor_text)
	_log("\n".join(lines))


func _cmd_chain() -> void:
	if gs.chain.is_empty():
		_log("[INFO] Chain is empty.")
		return
	_log("[INFO] Chain (top → bottom):")
	for i in range(gs.chain.size() - 1, -1, -1):
		_log("  [%d] %s" % [i, gs.chain[i].describe()])


func _cmd_score() -> void:
	_log("[INFO] Score: P1=%d | P2=%d | Victory: %d pts" % [
		gs.players[0].score, gs.players[1].score, gs.victory_score
	])


func _cmd_pool(player_index: int) -> void:
	var ps: PlayerState = gs.players[player_index]
	var rune_list: Array[String] = []
	for i in range(ps.channeled_runes.size()):
		var r = ps.channeled_runes[i]
		var d = CardDefinition._domain_abbr(r.definition.domain[0]) if r.definition.domain.size() > 0 else "?"
		rune_list.append("rune-%d(%s%s)" % [i, d, "/EXH" if r.is_exhausted else ""])
	_log("[INFO] P%d Pool: %s" % [player_index + 1, ps.rune_pool.describe()])
	if not rune_list.is_empty():
		_log("[INFO] P%d Runes: %s" % [player_index + 1, ", ".join(rune_list)])


func _cmd_zones() -> void:
	for i in range(gs.players.size()):
		var ps: PlayerState = gs.players[i]
		_log("[INFO] P%d zones: deck=%d | hand=%d | rune_deck=%d | runes_on_board=%d | trash=%d | ban=%d" % [
			i + 1, ps.deck.size(), ps.hand.size(), ps.rune_deck.size(),
			ps.channeled_runes.size(), ps.trash.size(), ps.banishment.size()
		])


func _cmd_help(player_index: int) -> void:
	var lines: Array[String] = [
		"[INFO] Available commands:",
		"  RESOURCES:  tap rune-<n>  |  recycle rune-<n>",
		"  CARDS:      play <id> [to <location>] [target <id>] [accelerate]",
		"              play <id> from champion  |  from hidden",
		"  MOVEMENT:   move <id> [id...] to <base|battlefield-a|battlefield-b>",
		"  ABILITIES:  use <id> [target <id>]",
		"  CHAIN:      react <id> [target <id>]  |  pass",
		"  TURN:       end turn",
		"  INFO:       hand  |  board  |  card <id>  |  chain  |  score  |  pool  |  zones",
		"  MULLIGAN:   mulligan <id> [id]  |  mulligan keep",
		"  OTHER:      new game",
	]
	for l in lines:
		_log(l)


# ─── Helpers ─────────────────────────────────────────────────────────────────

func _check_can_act(player_index: int) -> bool:
	if not gs.can_player_act(player_index):
		_log("[ERROR] Not your turn to act — waiting for P%d" % (gs.priority_player_index + 1))
		return false
	return true


func _find_player_permanent(player_index: int, inst_id: String) -> CardInstance:
	var ps: PlayerState = gs.players[player_index]
	var c = ps.get_board_instance(inst_id)
	if c:
		return c
	# Also search battlefields
	var u = gs.board.find_unit_on_board(inst_id)
	if u and u.owner_index == player_index:
		return u
	return null


func _build_target_prompt(card: CardInstance, ab: Dictionary, player_index: int, game_state: GameState) -> String:
	var target_filter = ab.get("effect_params", {}).get("target", "any")
	return "[PROMPT] Choose a target for %s (filter: %s) — use: choose <id>" % [
		card.definition.name, target_filter
	]


func _log(text: String) -> void:
	game_log_message.emit(text)
	print(text)


func _maybe_trigger_ai() -> void:
	if _ai_player_index < 0:
		return
	if gs.game_over or gs.mulligan_phase:
		return
	if gs.current_phase != TurnStateMachine.Phase.MAIN:
		return
	if gs.can_player_act(_ai_player_index):
		# Defer to next frame to avoid re-entrancy
		call_deferred("_trigger_ai_turn")


func _trigger_ai_turn() -> void:
	var ai_node = get_node_or_null("AIPlayer")
	if ai_node:
		ai_node.take_turn()
