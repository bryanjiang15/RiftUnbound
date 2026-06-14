class_name GameController
extends Node

const TriggerDispatcherScript = preload("res://Scripts/Game/TriggerDispatcher.gd")
const TargetResolverScript = preload("res://Scripts/Game/TargetResolver.gd")
const ConditionEvaluatorScript = preload("res://Scripts/Game/ConditionEvaluator.gd")

signal board_updated
signal game_log_message(text: String)

const P1_DECK = "res://Data/Decks/starter-deck-p1.json"
const P2_DECK = "res://Data/Decks/starter-deck-p2.json"

var gs: GameState = GameState.new()
var ability_resolver: AbilityResolver = AbilityResolver.new()
var trigger_dispatcher: TriggerDispatcher = TriggerDispatcherScript.new()

var skip_auto_start: bool = false
var log_lines: Array[String] = []

var _ai_player_index: int = 1  # which player is AI (-1 = human vs human)

# Set to true if the most recent submit_command call logged an [ERROR].
# AIPlayer reads this to detect genuine move rejections vs. normal "still my turn".
var last_command_error: bool = false


func _ready() -> void:
	if skip_auto_start:
		return
	start_game()


func start_game() -> void:
	start_game_from_config({})


func start_game_from_config(config: Dictionary) -> void:
	log_lines.clear()
	gs = GameState.new()
	gs.players.clear()
	_first_player_cache = -1

	if config.has("seed"):
		seed(int(config["seed"]))

	var p1_path = config.get("p1_deck", P1_DECK)
	var p2_path = config.get("p2_deck", P2_DECK)
	var p1 = DeckLoader.build_player_state(p1_path, 0)
	var p2 = DeckLoader.build_player_state(p2_path, 1)
	if p1 == null or p2 == null:
		_log("[ERROR] Failed to load decks. Check Data/Decks/ paths.")
		return
	gs.players.append(p1)
	gs.players.append(p2)
	gs.game_session_id = str(config.get("game_session_id", _generate_game_session_id(p1.player_name, p2.player_name)))

	var bf_list: Array = config.get("battlefields", [])
	var p1_bf: String
	var p2_bf: String
	if bf_list.size() >= 2:
		p1_bf = str(bf_list[0])
		p2_bf = str(bf_list[1])
	else:
		p1_bf = p1.deck_battlefields[0]
		p2_bf = p2.deck_battlefields[0]
		if p1_bf == p2_bf and p1.deck_battlefields.size() > 1:
			p2_bf = p1.deck_battlefields[1]
	gs.board.setup(p1_bf, p2_bf)

	gs.turn_player_index = int(config.get("first_player", randi() % 2))
	gs.priority_player_index = gs.turn_player_index
	gs.second_player_index = 1 - gs.turn_player_index if config.is_empty() else int(config.get("second_player", 1 - gs.turn_player_index))
	gs.first_channel_done[gs.turn_player_index] = false
	gs.first_channel_done[1 - gs.turn_player_index] = false
	_first_player_cache = gs.turn_player_index

	_log("> Riftbound 1v1 — %s vs %s" % [p1.player_name, p2.player_name])
	_log("> Session: %s" % gs.game_session_id)
	_log("> Battlefields: %s and %s" % [
		gs.board.battlefields[0].display_name,
		gs.board.battlefields[1].display_name
	])
	_log("> P%d goes first" % (gs.turn_player_index + 1))

	if config.get("skip_mulligan", false):
		gs.mulligan_phase = false
		gs.mulligan_done[0] = true
		gs.mulligan_done[1] = true
		if config.has("turn_number"):
			gs.turn_number = int(config["turn_number"])
		return

	for ps in gs.players:
		for _i in range(4):
			var drawn = ps.draw_card()
			if drawn:
				_log("> [P%d] Drew %s" % [ps.player_index + 1, drawn.display_name()])

	gs.mulligan_phase = true
	gs.mulligan_done[0] = false
	gs.mulligan_done[1] = false
	_log("> Mulligan: each player may set aside up to 2 cards.")
	_log("[PROMPT] P1 goes first — type: mulligan keep  |  mulligan <id> [id]")
	_log("[PROMPT] P2 goes after  — type: mulligan keep  |  mulligan <id> [id]")

	board_updated.emit()


static func _generate_game_session_id(p1_name: String, p2_name: String) -> String:
	# Readable prefix + unix time + random suffix — unique per start_game_from_config call.
	return "%s-vs-%s-%d-%x" % [p1_name, p2_name, Time.get_unix_time_from_system(), randi()]


# ─── Public entry point ──────────────────────────────────────────────────────

func submit_command(player_index: int, raw: String) -> void:
	last_command_error = false
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
		"hide":
			_cmd_hide(player_index, args)
		"equip":
			_cmd_equip(player_index, args)
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
		"menu":
			get_tree().change_scene_to_file("res://Scenes/MainMenu.tscn")
			return
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

	# Beginning Phase — triggers before Hold scoring
	gs.current_phase = TurnStateMachine.Phase.BEGINNING
	_log("> Beginning Phase")
	_kill_temporary_units(turn_pi)
	var trig_ctx = {"player_index": turn_pi, "controller": self}
	for line in trigger_dispatcher.emit("beginning_phase_start", trig_ctx, gs, self):
		_log(line)
	trigger_dispatcher.emit_passive_auras(gs)
	# Scoring Step: Hold
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
		if turn_pi == gs.second_player_index:
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

	# Expiration Step
	CleanupProcessor.heal_all_units(gs)
	CleanupProcessor.expire_turn_effects(gs)
	for line in trigger_dispatcher.process_end_of_turn(gs, self):
		_log(line)
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
			lines = CombatProcessor.handle_pass(gs, self)
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
		var lines = ChainProcessor.handle_pass(gs, ability_resolver, self)
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
	var in_main = gs.current_phase == TurnStateMachine.Phase.MAIN
	var in_showdown = gs.is_showdown_state()
	if not in_main and not in_showdown:
		_log("[ERROR] Can only play cards during Main Phase or Showdown.")
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

	# Units to base unless Ambush allows battlefield deployment
	if card.definition.card_type == "unit" and destination.begins_with("battlefield"):
		if not card.has_keyword("ambush"):
			_log("[ERROR] Units must be played to base. Direct battlefield deployment requires Ambush.")
			return

	var optional_disc_ab = _find_optional_discard_discount_ability(card)
	if optional_disc_ab.is_empty() and not use_accelerate and gs.pending_prompt.is_empty():
		var optional_accel_ab = _find_optional_accelerate_ability(card)
		if not optional_accel_ab.is_empty():
			gs.pending_prompt = {
				"player_index": player_index,
				"type": "choose_optional",
				"ability": optional_accel_ab,
				"source": card,
				"ctx": {},
				"valid_choices": ["yes", "no"],
				"prompt": "[PROMPT] Pay Accelerate on %s (+1 ENG and 1 domain Power to enter Ready)? (choose yes or no)" % card.display_name(),
				"play_resume": {
					"card_id": card.instance_id,
					"player_index": player_index,
					"destination": destination,
					"target_id": target_id,
					"from_zone": from_zone,
					"use_accelerate": false,
					"await_accelerate": true,
				},
			}
			_log(gs.pending_prompt["prompt"])
			return

	if not optional_disc_ab.is_empty() and gs.pending_prompt.is_empty():
		gs.pending_prompt = {
			"player_index": player_index,
			"type": "choose_optional",
			"ability": optional_disc_ab,
			"source": card,
			"ctx": {},
			"valid_choices": ["yes", "no"],
			"prompt": "[PROMPT] %s — discard 1 to reduce cost by 2? (choose yes or no)" % card.display_name(),
			"play_resume": {
				"card_id": card.instance_id,
				"player_index": player_index,
				"destination": destination,
				"target_id": target_id,
				"from_zone": from_zone,
				"use_accelerate": use_accelerate,
			},
		}
		_log(gs.pending_prompt["prompt"])
		return

	_complete_play(card, player_index, destination, target_id, from_zone, use_accelerate, false)


func _kill_temporary_units(turn_pi: int) -> void:
	for ps in gs.players:
		var to_kill: Array = []
		for u in ps.get_units_at_base():
			if u.has_keyword("temporary") and u.owner_index == turn_pi:
				to_kill.append(u)
		for u in gs.board.get_all_units_on_board(ps.player_index):
			if u.has_keyword("temporary") and u.owner_index == turn_pi:
				to_kill.append(u)
		for u in to_kill:
			_log("> %s (Temporary) is killed at Beginning Phase" % u.display_name())
			gs.board.remove_unit_from_battlefield(u)
			ps.move_to_trash(u)


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
				var valid = TargetResolverScript.filter_with_params(
					item.target_filter, ab.get("effect_params", {}), card, gs,
					{"player_index": player_index}
				)
				item.valid_targets = valid
				break

	gs.push_to_chain(item)
	_log("> %s added to Chain" % card.definition.name)

	var chain_lines = ChainProcessor.on_card_added_to_chain(gs)
	for l in chain_lines:
		_log(l)


func _find_optional_discard_discount_ability(card: CardInstance) -> Dictionary:
	for ab in card.definition.abilities:
		if ab.get("timing", "") != "on_play" or not ab.get("is_optional", false):
			continue
		if ab.get("effect_type", "") != "cost_reduction":
			continue
		if int(ab.get("cost", {}).get("discard", 0)) > 0:
			return ab
	return {}


func _find_optional_accelerate_ability(card: CardInstance) -> Dictionary:
	for ab in card.definition.abilities:
		if ab.get("timing", "") != "on_play" or not ab.get("is_optional", false):
			continue
		if ab.get("effect_type", "") != "enter_ready":
			continue
		if card.has_keyword("accelerate"):
			return ab
	return {}


func _complete_play(
	card: CardInstance,
	player_index: int,
	destination: String,
	target_id: String,
	from_zone: String,
	use_accelerate: bool,
	optional_discard_discount: bool,
	declined_accelerate: bool = false
) -> void:
	var ps: PlayerState = gs.players[player_index]
	var cost = CostCalculator.compute_play_cost(card, player_index, gs, use_accelerate, optional_discard_discount)
	if not try_pay_cost(player_index, cost):
		_log("[ERROR] Cannot play %s: insufficient resources (need %s, pool: %s)" % [
			card.definition.name, CostCalculator.cost_to_string(cost),
			ps.rune_pool.describe()
		])
		return
	ps.cards_played_this_turn += 1
	card.played_this_turn = true

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

	if card.definition.card_type != "spell":
		_fire_on_play_triggers(card, use_accelerate, declined_accelerate)

	if gs.pending_prompt.is_empty():
		_run_cleanup()


func _complete_play_from_resume(play_resume: Dictionary, optional_discard_discount: bool) -> void:
	var card_id: String = play_resume.get("card_id", "")
	var player_index: int = int(play_resume.get("player_index", 0))
	var card = gs.find_instance_anywhere(card_id)
	if card == null:
		_log("[ERROR] Cannot resume play — card '%s' not found." % card_id)
		return
	_complete_play(
		card,
		player_index,
		play_resume.get("destination", ""),
		play_resume.get("target_id", ""),
		play_resume.get("from_zone", "hand"),
		play_resume.get("use_accelerate", false),
		optional_discard_discount,
		play_resume.get("declined_accelerate", false),
	)


func _fire_on_play_triggers(card: CardInstance, use_accelerate: bool = false, declined_accelerate: bool = false) -> void:
	var ctx = {
		"player_index": card.owner_index,
		"controller": self,
		"source": card,
		"use_accelerate": use_accelerate,
		"declined_accelerate": declined_accelerate,
	}
	for line in trigger_dispatcher.emit("on_play", ctx, gs, self):
		_log(line)
		if not gs.pending_prompt.is_empty():
			return
	for ab in card.definition.abilities:
		if ab.get("effect_type", "") == "other_friendly_units_enter_ready":
			for line in ability_resolver.resolve_ability(ab, card, null, gs, ctx):
				_log(line)
			if not gs.pending_prompt.is_empty():
				return


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
			# Check if this triggers contested:
			# - opponent controls it, OR
			# - it is uncontrolled (player must claim it via showdown), OR
			# - opponent already has units there
			var bf = gs.board.battlefields[dest_bf_idx]
			if bf.controller_index != player_index or not bf.units[1 - player_index].is_empty():
				bf.is_contested = true
				gs.attacker_player_index = player_index
				_log("> %s is now Contested" % bf.display_name)
			var move_ctx = {
				"player_index": player_index,
				"source": unit,
				"battlefield_index": dest_bf_idx if destination != "base" else -1,
				"controller": self,
			}
			for line in trigger_dispatcher.emit("on_move", move_ctx, gs, self):
				_log(line)

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

	# Find an activated ability (including attach)
	var ab: Dictionary = {}
	for a in card.definition.abilities:
		if a.get("ability_type", "") == "activated":
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
	if target == null and ab.get("effect_params", {}).get("target", "") == "self":
		target = card

	var cost = CostCalculator.compute_ability_cost(ab, card, target, gs)
	if not try_pay_cost(player_index, cost, card):
		_log("[ERROR] Cannot afford ability cost: %s" % CostCalculator.cost_to_string(cost))
		return

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
	if not try_pay_cost(player_index, cost):
		_log("[ERROR] Cannot afford %s (need %s, pool: %s)" % [
			card.definition.name, CostCalculator.cost_to_string(cost),
			ps.rune_pool.describe()
		])
		return
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
	if not gs.combat_assignment_active:
		_log("[ERROR] Not in combat damage assignment.")
		return
	if player_index != gs.attacker_player_index:
		_log("[ERROR] Only the attacker assigns damage.")
		return
	if args.is_empty():
		_log("[ERROR] Usage: assign <amount> to <id>  |  assign done")
		return
	if args[0] == "done":
		var lines = CombatProcessor.finalize_assignments(gs, self)
		for l in lines:
			_log(l)
		_run_cleanup()
		return
	if args.size() < 3 or args[1] != "to":
		_log("[ERROR] Usage: assign <amount> to <id>")
		return
	var amount = int(args[0])
	var target_id = args[2]
	var bf = gs.board.battlefields[gs.combat_bf_index]
	var defender = 1 - gs.attacker_player_index
	var target = null
	for u in bf.units[defender]:
		if u.instance_id == target_id:
			target = u
			break
	if target == null:
		_log("[ERROR] Target '%s' not found." % target_id)
		return
	gs.damage_assignments[target_id] = int(gs.damage_assignments.get(target_id, 0)) + amount
	gs.remaining_attacker_might -= amount
	_log("> Assigned %d damage to %s (%d remaining)" % [amount, target.display_name(), gs.remaining_attacker_might])


# ─── Discard orchestration ────────────────────────────────────────────────────

func begin_discard(
	player_index: int,
	amount: int,
	continuation: Dictionary,
	source: Variant = null,
	ability: Dictionary = {}
) -> Array:
	var ps: PlayerState = gs.players[player_index]
	if amount <= 0 or ps.hand.is_empty():
		_dispatch_discard_continuation(continuation)
		return []
	var valid_choices: Array = []
	for card in ps.hand:
		valid_choices.append(card.instance_id)
	var remaining = mini(amount, ps.hand.size())
	gs.pending_prompt = {
		"player_index": player_index,
		"type": "choose_discard",
		"remaining": remaining,
		"mandatory": true,
		"continuation": continuation,
		"valid_choices": valid_choices,
		"source": source,
		"ability": ability,
		"prompt": "[PROMPT] Choose a card to discard (%d remaining) (use: choose <id>)" % remaining,
	}
	return [gs.pending_prompt["prompt"]]


func _dispatch_discard_continuation(continuation: Dictionary) -> void:
	if continuation.is_empty():
		return
	match continuation.get("kind", ""):
		"discard_then_draw":
			var owner = int(continuation.get("owner", 0))
			var draw_amount = int(continuation.get("draw_amount", 1))
			for line in ability_resolver.resolve_ability(
				{"effect_type": "draw", "effect_params": {"amount": draw_amount}},
				null, null, gs, {"player_index": owner, "controller": self}
			):
				_log(line)
		"chain_after_discard_cost":
			_finish_chain_after_discard_cost(continuation)
		"trigger_after_discard_cost":
			var ab: Dictionary = continuation.get("ability", {})
			var source = continuation.get("source")
			var ctx: Dictionary = continuation.get("ctx", {})
			var computed: Dictionary = continuation.get("computed", {})
			var owner_pi = int(ctx.get("player_index", 0))
			if source is CardInstance:
				owner_pi = source.owner_index
			if try_pay_cost(owner_pi, _cost_after_discard_paid(computed), source if source is CardInstance else null):
				var target = trigger_dispatcher._resolve_trigger_target(ab, source, ctx, gs)
				var effect_ctx = ctx.duplicate()
				effect_ctx["controller"] = self
				for line in ability_resolver.resolve_ability(ab, source, target, gs, effect_ctx):
					_log(line)
		"brazen_play":
			_complete_play_from_resume(continuation.get("play_resume", {}), true)
		"optional_after_discard_cost":
			var ab2: Dictionary = continuation.get("ability", {})
			var source2 = continuation.get("source")
			var ctx2: Dictionary = continuation.get("ctx", {})
			var computed2: Dictionary = continuation.get("computed", {})
			var owner2 = int(ctx2.get("player_index", 0))
			if source2 is CardInstance:
				owner2 = source2.owner_index
			if try_pay_cost(owner2, _cost_after_discard_paid(computed2), source2 if source2 is CardInstance else null):
				var target2 = trigger_dispatcher._resolve_trigger_target(ab2, source2, ctx2, gs)
				var effect_ctx2 = ctx2.duplicate()
				effect_ctx2["controller"] = self
				for line in ability_resolver.resolve_ability(ab2, source2, target2, gs, effect_ctx2):
					_log(line)


func _finish_chain_after_discard_cost(continuation: Dictionary) -> void:
	var item: ChainItem = continuation.get("chain_item")
	var ab: Dictionary = continuation.get("ability", {})
	var target: CardInstance = continuation.get("target")
	var computed: Dictionary = continuation.get("computed", {})
	if item == null:
		return
	var owner_pi = item.owner_index
	var card = item.source_card
	if not try_pay_cost(owner_pi, _cost_after_discard_paid(computed), card):
		return
	var ctx = {"controller": self, "player_index": owner_pi}
	for line in ability_resolver.resolve_ability(ab, card, target, gs, ctx):
		_log(line)
	if card != null and card.definition.card_type == "spell":
		gs.players[owner_pi].move_to_trash(card)
	if gs.chain.is_empty():
		for l in ChainProcessor._return_to_open(gs):
			_log(l)
	else:
		gs.passes_in_sequence = 0
		gs.priority_player_index = 1 - owner_pi
		_log("[PROMPT] P%d: play Reaction or 'pass'" % (gs.priority_player_index + 1))


func _resume_discard_prompt(prompt: Dictionary) -> void:
	var remaining = int(prompt.get("remaining", 1))
	var player_index = int(prompt.get("player_index", 0))
	var ps = gs.players[player_index]
	if remaining > 0 and not ps.hand.is_empty():
		var valid_choices: Array = []
		for card in ps.hand:
			valid_choices.append(card.instance_id)
		gs.pending_prompt = prompt.duplicate()
		gs.pending_prompt["valid_choices"] = valid_choices
		gs.pending_prompt["prompt"] = "[PROMPT] Choose a card to discard (%d remaining) (use: choose <id>)" % remaining
		_log(gs.pending_prompt["prompt"])
	else:
		var continuation = prompt.get("continuation", {})
		_dispatch_discard_continuation(continuation)


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

	match prompt_type:
		"choose_target":
			_handle_choose_target(player_index, choice)
		"choose_discard":
			_handle_choose_discard(player_index, choice)
		"choose_trash_return":
			_handle_choose_trash_return(player_index, choice)
		"choose_optional":
			_handle_choose_optional(player_index, choice)
		"choose_battlefield":
			_handle_choose_battlefield(player_index, choice)
		_:
			_log("[ERROR] Unknown prompt type: %s" % prompt_type)


func _handle_choose_target(player_index: int, choice: String) -> void:
	var item: ChainItem = gs.pending_prompt.get("chain_item")
	if item == null:
		gs.pending_prompt.clear()
		return
	var valid: Array = gs.pending_prompt.get("valid_choices", [])
	if not valid.is_empty():
		var allowed := false
		for v in valid:
			if v is CardInstance and v.instance_id == choice:
				allowed = true
				break
			if str(v) == choice:
				allowed = true
				break
		if not allowed:
			_log("[ERROR] '%s' is not a valid target." % choice)
			return
	var target = gs.find_instance_anywhere(choice)
	if target == null:
		_log("[ERROR] Target '%s' not found." % choice)
		return
	var ab_params = {}
	for ab in item.source_card.definition.abilities:
		if ab.get("timing", "") == "resolution":
			ab_params = ab.get("effect_params", {})
			break
	if not ab_params.is_empty() and not ConditionEvaluatorScript.evaluate_target_filter(ab_params, target, item.source_card, gs):
		_log("[ERROR] Invalid target '%s'." % choice)
		return
	item.targets = [target]
	item.needs_target = false
	gs.pending_prompt.clear()
	_log("> P%d chose %s as target" % [player_index + 1, target.display_name()])
	var resolve_lines = ChainProcessor.resolve_chain_item(item, gs, ability_resolver, self)
	for l in resolve_lines:
		_log(l)
	_run_cleanup()


func _handle_choose_discard(player_index: int, choice: String) -> void:
	var prompt = gs.pending_prompt.duplicate()
	gs.pending_prompt.clear()
	var ps = gs.players[player_index]
	var card = ps.get_hand_instance(choice)
	if card == null:
		_log("[ERROR] '%s' not in hand." % choice)
		_resume_discard_prompt(prompt)
		return
	ps.move_to_trash(card)
	ps.cards_discarded_count += 1
	ps.discarded_this_turn.append(card)
	_log("> P%d discarded %s" % [player_index + 1, card.display_name()])
	for line in trigger_dispatcher.emit("on_discard", {
		"discarded_card": card,
		"player_index": player_index,
		"controller": self,
		"discard_resume": prompt,
	}, gs, self):
		_log(line)
		if not gs.pending_prompt.is_empty():
			return
	var remaining = int(prompt.get("remaining", 1)) - 1
	gs.pending_prompt.clear()
	if remaining > 0 and not ps.hand.is_empty():
		prompt["remaining"] = remaining
		_resume_discard_prompt(prompt)
		return
	_dispatch_discard_continuation(prompt.get("continuation", {}))
	_run_cleanup()


func _handle_choose_trash_return(player_index: int, choice: String) -> void:
	var ps = gs.players[player_index]
	var card = ps.find_instance(choice)
	if card == null or not card in ps.trash:
		_log("[ERROR] '%s' not in trash." % choice)
		return
	ps.move_to_hand(card)
	gs.pending_prompt.clear()
	_log("> P%d returned %s from trash" % [player_index + 1, card.display_name()])
	_run_cleanup()


func _handle_choose_optional(player_index: int, choice: String) -> void:
	var prompt = gs.pending_prompt.duplicate()
	var ab: Dictionary = prompt.get("ability", {})
	var source = prompt.get("source")
	var ctx: Dictionary = prompt.get("ctx", {})
	var play_resume: Dictionary = prompt.get("play_resume", {})
	gs.pending_prompt.clear()

	if not play_resume.is_empty():
		if play_resume.get("await_accelerate", false):
			var use_accel := choice == "yes" or choice == "true"
			if use_accel:
				_log("> P%d chose Accelerate on %s" % [player_index + 1, source.display_name() if source is CardInstance else "card"])
			else:
				_log("> P%d declined Accelerate" % (player_index + 1))
				play_resume["declined_accelerate"] = true
			play_resume["use_accelerate"] = use_accel
			play_resume.erase("await_accelerate")
			_complete_play_from_resume(play_resume, false)
			return
		if choice == "yes" or choice == "true":
			var card = source if source is CardInstance else gs.find_instance_anywhere(play_resume.get("card_id", ""))
			for line in begin_discard(player_index, 1, {
				"kind": "brazen_play",
				"play_resume": play_resume,
			}, card, ab):
				_log(line)
		else:
			_log("> P%d declined optional discard discount" % (player_index + 1))
			_complete_play_from_resume(play_resume, false)
			_run_cleanup()
		return

	if choice == "yes" or choice == "true":
		var cost = ab.get("cost", {})
		if not cost.is_empty():
			var computed = CostCalculator.compute_ability_cost(cost, source if source is CardInstance else null, null, gs)
			var discard_n = CostCalculator.discard_count(computed)
			if discard_n > 0:
				for line in begin_discard(player_index, discard_n, {
					"kind": "optional_after_discard_cost",
					"ability": ab,
					"source": source,
					"ctx": ctx,
					"computed": computed,
				}, source if source is CardInstance else null, ab):
					_log(line)
				return
			if not try_pay_cost(player_index, computed, source if source is CardInstance else null):
				_log("[ERROR] Cannot afford optional ability cost: %s" % CostCalculator.cost_to_string(computed))
				_run_cleanup()
				return
		var target = trigger_dispatcher._resolve_trigger_target(ab, source, ctx, gs)
		var effect_ctx = ctx.duplicate()
		effect_ctx["controller"] = self
		for line in ability_resolver.resolve_ability(ab, source, target, gs, effect_ctx):
			_log(line)
	else:
		_log("> P%d declined optional ability" % (player_index + 1))

	var discard_resume: Dictionary = prompt.get("discard_resume", {})
	if discard_resume.is_empty() and not ctx.is_empty():
		discard_resume = ctx.get("discard_resume", {})
	if not discard_resume.is_empty():
		var remaining = int(discard_resume.get("remaining", 1)) - 1
		discard_resume["remaining"] = remaining
		if remaining > 0 and not gs.players[player_index].hand.is_empty():
			_resume_discard_prompt(discard_resume)
		else:
			_dispatch_discard_continuation(discard_resume.get("continuation", {}))
	elif prompt.has("resume_on_play"):
		var resume: Dictionary = prompt.get("resume_on_play", {})
		for line in trigger_dispatcher.resume_on_play(
			resume.get("ctx", {}), gs, self, int(resume.get("next_index", 0))
		):
			_log(line)
			if not gs.pending_prompt.is_empty():
				_run_cleanup()
				return
	_run_cleanup()


func _handle_choose_battlefield(player_index: int, choice: String) -> void:
	var bf_idx = gs.board.get_battlefield_index(choice)
	if bf_idx < 0:
		_log("[ERROR] Unknown battlefield '%s'." % choice)
		return
	gs.pending_prompt.clear()
	if bf_idx in gs.board.staged_combats:
		gs.board.staged_combats.erase(bf_idx)
		for line in CombatProcessor.begin_combat(bf_idx, gs.attacker_player_index, gs, self):
			_log(line)
	elif bf_idx in gs.board.staged_showdowns:
		gs.board.staged_showdowns.erase(bf_idx)
		for line in ShowdownProcessor.begin_showdown(bf_idx, gs.turn_player_index, gs):
			_log(line)
	_run_cleanup()


func _cmd_hide(player_index: int, args: Array) -> void:
	if not _check_can_act(player_index):
		return
	# hide <id> at <battlefield>
	if args.size() < 3 or args[1] != "at":
		_log("[ERROR] Usage: hide <card-id> at <battlefield-a|battlefield-b>")
		return
	var card_id = args[0]
	var bf_id = args[2]
	var ps = gs.players[player_index]
	var card = ps.get_hand_instance(card_id)
	if card == null:
		_log("[ERROR] '%s' not in hand." % card_id)
		return
	if not card.has_keyword("hidden") and not card.definition.has_keyword("hidden"):
		_log("[ERROR] %s does not have Hidden." % card.definition.name)
		return
	var bf_idx = gs.board.get_battlefield_index(bf_id)
	if bf_idx < 0:
		_log("[ERROR] Unknown battlefield.")
		return
	var bf = gs.board.battlefields[bf_idx]
	if bf.controller_index != player_index:
		_log("[ERROR] You must control that battlefield to hide a card there.")
		return
	if bf.facedown_card != null:
		_log("[ERROR] Facedown zone already occupied.")
		return
	ps.hand.erase(card)
	card.is_face_down = true
	card.location = bf_id
	bf.facedown_card = card
	_log("> P%d hid %s at %s" % [player_index + 1, card.definition.name, bf.display_name])
	_run_cleanup()


func _cmd_equip(player_index: int, args: Array) -> void:
	if args.size() >= 3 and args[1] == "target":
		_cmd_use(player_index, [args[0], "target", args[2]])
	else:
		_log("[ERROR] Usage: equip <gear-id> target <unit-id>")


# ─── Cleanup helper ─────────────────────────────────────────────────────────

func _run_cleanup() -> void:
	var lines = CleanupProcessor.run(gs, ability_resolver, self)
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
	var valid = TargetResolverScript.filter_with_params(target_filter, ab.get("effect_params", {}), card, game_state, {"player_index": player_index})
	var ids: Array[String] = []
	for t in valid:
		ids.append(t.instance_id)
	return "[PROMPT] Choose a target for %s — use: choose <%s>" % [
		card.definition.name, "|".join(ids) if not ids.is_empty() else "id"
	]


# ─── Auto-pay ────────────────────────────────────────────────────────────────
# Pay from the Rune Pool, recycling/tapping channeled runes first when the pool
# is short on domain Power or Energy.

func _cost_after_discard_paid(cost: Dictionary) -> Dictionary:
	var remaining = cost.duplicate()
	remaining["discard"] = 0
	return remaining


func try_pay_cost(player_index: int, cost: Dictionary, source: CardInstance = null) -> bool:
	if cost.is_empty():
		return true
	if not CostCalculator.can_afford(player_index, cost, gs):
		_auto_pay_runes(player_index, cost)
	if not CostCalculator.can_afford(player_index, cost, gs):
		return false
	CostCalculator.pay_cost(player_index, cost, source, gs)
	return true


func _auto_pay_runes(player_index: int, cost: Dictionary) -> void:
	var ps: PlayerState = gs.players[player_index]

	# 1. Specific domain power requirements — recycle matching runes.
	for pc in cost.get("power", []):
		var domain: String = pc.get("domain", "")
		if domain == "any":
			continue
		var need: int = maxi(0, pc.get("amount", 0) - ps.rune_pool.power.get(domain, 0))
		for _i in range(need):
			var rune = _find_rune_for_recycle_domain(ps, domain)
			if rune != null:
				_auto_recycle_rune(player_index, rune)

	# 2. "Any" domain power requirements — recycle any rune.
	for pc in cost.get("power", []):
		if pc.get("domain", "") != "any":
			continue
		var need: int = maxi(0, pc.get("amount", 0) - ps.rune_pool.total_power())
		for _i in range(need):
			var rune = _find_rune_for_recycle_any(ps)
			if rune != null:
				_auto_recycle_rune(player_index, rune)

	# 3. Energy requirement — tap untapped runes.
	var energy_need: int = maxi(0, cost.get("energy", 0) - ps.rune_pool.energy)
	for _i in range(energy_need):
		var rune = _find_untapped_rune(ps)
		if rune != null:
			_auto_tap_rune(player_index, rune)


func _find_rune_for_recycle_domain(ps: PlayerState, domain: String) -> CardInstance:
	# Prefer already-exhausted runes of the domain (they can't supply energy anyway).
	for rune in ps.channeled_runes:
		if rune.is_exhausted and domain in rune.definition.domain:
			return rune
	for rune in ps.channeled_runes:
		if not rune.is_exhausted and domain in rune.definition.domain:
			return rune
	return null


func _find_rune_for_recycle_any(ps: PlayerState) -> CardInstance:
	for rune in ps.channeled_runes:
		if rune.is_exhausted:
			return rune
	for rune in ps.channeled_runes:
		return rune
	return null


func _find_untapped_rune(ps: PlayerState) -> CardInstance:
	for rune in ps.channeled_runes:
		if not rune.is_exhausted:
			return rune
	return null


func _auto_tap_rune(player_index: int, rune: CardInstance) -> void:
	for ab in rune.definition.abilities:
		if ab.get("effect_type", "") == "add_energy":
			if ab.get("cost", {}).get("exhaust", false):
				rune.exhaust()
			var lines = ability_resolver.resolve_ability(ab, rune, null, gs)
			for l in lines:
				_log(l)
			return


func _auto_recycle_rune(player_index: int, rune: CardInstance) -> void:
	if not rune.is_exhausted:
		_auto_tap_rune(player_index, rune)
	for ab in rune.definition.abilities:
		if ab.get("effect_type", "") == "add_power":
			CostCalculator.pay_cost(player_index, ab.get("cost", {}), rune, gs)
			var lines = ability_resolver.resolve_ability(ab, rune, null, gs)
			for l in lines:
				_log(l)
			_log("> [Auto] Rune recycled to bottom of Rune Deck")
			return


func _log(text: String) -> void:
	log_lines.append(text)
	if text.begins_with("[ERROR]"):
		last_command_error = true
	game_log_message.emit(text)
	print(text)


func _maybe_trigger_ai() -> void:
	if _ai_player_index < 0 or gs.game_over:
		return
	# Mulligan is outside the normal turn-state machine; handle it separately.
	if gs.mulligan_phase:
		if not gs.mulligan_done[_ai_player_index]:
			call_deferred("_trigger_ai_turn")
		return
	# Trigger for every situation where the AI seat has the right to act:
	# main phase priority, showdown focus, chain reactions, pending prompts,
	# and combat damage assignment all route through can_player_act().
	if gs.can_player_act(_ai_player_index):
		call_deferred("_trigger_ai_turn")


func _trigger_ai_turn() -> void:
	var ai_node = get_node_or_null("AIPlayer")
	if ai_node:
		ai_node.take_turn()
