class_name GameState

# Players
var players: Array = []  # Array[PlayerState], 2 elements

# Board
var board: BoardState = BoardState.new()

# Chain (stack)
var chain: Array = []  # Array[ChainItem]

# Turn tracking
var turn_number: int = 1
var turn_player_index: int = 0
var current_phase: int = TurnStateMachine.Phase.AWAKEN
var current_state: int = TurnStateMachine.State.NEUTRAL_OPEN
var priority_player_index: int = 0
var focus_player_index: int = -1
var passes_in_sequence: int = 0

# Game outcome
var game_over: bool = false
var winner_index: int = -1
var victory_score: int = 8

# Pending prompt for player choices
var pending_prompt: Dictionary = {}

# Mulligan state
var mulligan_phase: bool = false
var mulligan_done: Array = [false, false]

# Combat/Showdown damage assignment
var combat_assignment_active: bool = false
var combat_bf_index: int = -1
var attacker_player_index: int = -1
var remaining_attacker_might: int = 0
var damage_assignments: Dictionary = {}  # instance_id -> amount
var assigned_targets: Array = []

# First turn bonus
var first_channel_done: Array = [false, false]


func get_turn_player() -> PlayerState:
	return players[turn_player_index]


func get_opponent(player_index: int) -> PlayerState:
	return players[1 - player_index]


func get_player(player_index: int) -> PlayerState:
	return players[player_index]


func find_instance_anywhere(inst_id: String) -> CardInstance:
	# Search hand, base, chain, battlefields
	for ps in players:
		var c = ps.find_instance(inst_id)
		if c:
			return c
	var c2 = board.find_unit_on_board(inst_id)
	if c2:
		return c2
	return null


func find_instance_on_board_or_hand(player_index: int, inst_id: String) -> CardInstance:
	var ps: PlayerState = players[player_index]
	var c = ps.get_hand_instance(inst_id)
	if c:
		return c
	c = ps.get_board_instance(inst_id)
	if c:
		return c
	c = board.find_unit_on_board(inst_id)
	if c and c.owner_index == player_index:
		return c
	return null


func all_units_on_board() -> Array:
	var result: Array = []
	for bf in board.battlefields:
		for player_units in bf.units:
			result.append_array(player_units)
	return result


func get_all_units_visible_to(player_index: int) -> Array:
	var result: Array = []
	result.append_array(all_units_on_board())
	var ps: PlayerState = players[player_index]
	result.append_array(ps.get_units_at_base())
	return result


func get_phase_name() -> String:
	return TurnStateMachine.phase_name(current_phase)


func get_state_name() -> String:
	return TurnStateMachine.state_name(current_state)


func is_open_state() -> bool:
	return current_state == TurnStateMachine.State.NEUTRAL_OPEN or \
		   current_state == TurnStateMachine.State.SHOWDOWN_OPEN


func is_showdown_state() -> bool:
	return current_state == TurnStateMachine.State.SHOWDOWN_OPEN or \
		   current_state == TurnStateMachine.State.SHOWDOWN_CLOSED


func can_player_act(player_index: int) -> bool:
	if pending_prompt.size() > 0:
		return pending_prompt.get("player_index", -1) == player_index
	if combat_assignment_active:
		return player_index == attacker_player_index
	if current_state == TurnStateMachine.State.NEUTRAL_OPEN:
		return player_index == turn_player_index
	if current_state == TurnStateMachine.State.NEUTRAL_CLOSED:
		return true  # reactions from anyone
	if current_state == TurnStateMachine.State.SHOWDOWN_OPEN:
		return player_index == focus_player_index
	if current_state == TurnStateMachine.State.SHOWDOWN_CLOSED:
		return true
	return false


func clear_chain() -> void:
	chain.clear()
	passes_in_sequence = 0


func push_to_chain(item: ChainItem) -> void:
	chain.append(item)
	passes_in_sequence = 0


func peek_chain() -> ChainItem:
	if chain.is_empty():
		return null
	return chain[chain.size() - 1]


func pop_chain() -> ChainItem:
	if chain.is_empty():
		return null
	return chain.pop_back()


func board_description() -> String:
	var lines: Array[String] = []
	lines.append("=== BOARD STATE ===")
	lines.append("Turn: %d | Phase: %s | State: %s" % [
		turn_number, get_phase_name(), get_state_name()
	])
	lines.append("Priority: P%d | Focus: %s" % [
		priority_player_index + 1,
		"P%d" % (focus_player_index + 1) if focus_player_index >= 0 else "none"
	])
	lines.append("")
	for i in range(players.size()):
		var ps: PlayerState = players[i]
		lines.append("--- P%d: %s ---" % [i + 1, ps.player_name])
		lines.append("  Score: %d | Deck: %d | Hand: %d | Rune Deck: %d" % [
			ps.score, ps.deck.size(), ps.hand.size(), ps.rune_deck.size()
		])
		lines.append("  Pool: %s" % ps.rune_pool.describe())
		var base_units = ps.get_units_at_base()
		if not base_units.is_empty():
			var unit_strs: Array[String] = []
			for u in base_units:
				unit_strs.append(u.short_description())
			lines.append("  Base units: " + ", ".join(unit_strs))
		var base_gear = ps.get_unattached_gear_at_base()
		if not base_gear.is_empty():
			var gear_strs: Array[String] = []
			for g in base_gear:
				gear_strs.append(g.instance_id)
			lines.append("  Base gear: " + ", ".join(gear_strs))
		if ps.champion_zone:
			lines.append("  Champion Zone: %s" % ps.champion_zone.short_description())
		var rune_strs: Array[String] = []
		for j in range(ps.channeled_runes.size()):
			var r = ps.channeled_runes[j]
			var domain_abbr = CardDefinition._domain_abbr(r.definition.domain[0]) if r.definition.domain.size() > 0 else "?"
			rune_strs.append("rune-%d(%s%s)" % [j, domain_abbr, "/EXH" if r.is_exhausted else ""])
		if not rune_strs.is_empty():
			lines.append("  Runes: " + ", ".join(rune_strs))
	lines.append("")
	lines.append("--- Battlefields ---")
	for i in range(board.battlefields.size()):
		lines.append(board.battlefield_description(i))
	if not chain.is_empty():
		lines.append("")
		lines.append("--- Chain ---")
		for i in range(chain.size() - 1, -1, -1):
			lines.append("  [%d] %s" % [i, chain[i].describe()])
	lines.append("===================")
	return "\n".join(lines)
