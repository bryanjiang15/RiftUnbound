class_name TurnStateMachine

enum Phase {
	AWAKEN = 0,
	BEGINNING = 1,
	CHANNEL = 2,
	DRAW = 3,
	MAIN = 4,
	ENDING = 5
}

enum State {
	NEUTRAL_OPEN = 0,
	NEUTRAL_CLOSED = 1,
	SHOWDOWN_OPEN = 2,
	SHOWDOWN_CLOSED = 3
}


static func phase_name(phase: int) -> String:
	match phase:
		Phase.AWAKEN: return "Awaken Phase"
		Phase.BEGINNING: return "Beginning Phase"
		Phase.CHANNEL: return "Channel Phase"
		Phase.DRAW: return "Draw Phase"
		Phase.MAIN: return "Main Phase"
		Phase.ENDING: return "Ending Phase"
	return "Unknown"


static func state_name(state: int) -> String:
	match state:
		State.NEUTRAL_OPEN: return "Neutral Open"
		State.NEUTRAL_CLOSED: return "Neutral Closed"
		State.SHOWDOWN_OPEN: return "Showdown Open"
		State.SHOWDOWN_CLOSED: return "Showdown Closed"
	return "Unknown"


static func can_play_card(card: CardInstance, state: int, player_index: int, game_state: GameState) -> bool:
	match card.definition.card_type:
		"unit", "gear":
			return state == State.NEUTRAL_OPEN and player_index == game_state.turn_player_index
		"spell":
			if card.definition.is_reaction:
				return (state == State.NEUTRAL_OPEN and player_index == game_state.turn_player_index) or \
					state == State.NEUTRAL_CLOSED or state == State.SHOWDOWN_OPEN or \
					state == State.SHOWDOWN_CLOSED
			if card.definition.is_action:
				return state == State.NEUTRAL_OPEN or state == State.SHOWDOWN_OPEN
			return state == State.NEUTRAL_OPEN and player_index == game_state.turn_player_index
		"rune":
			return false  # runes are channeled, not played
	return false


static func can_play_from_hidden(card: CardInstance, state: int, player_index: int, game_state: GameState) -> bool:
	if card == null:
		return false
	if card.owner_index != player_index:
		return false
	if not card.is_face_down:
		return false
	# Hidden cards become playable beginning on the next turn.
	if card.hidden_turn_number >= 0 and game_state.turn_number <= card.hidden_turn_number:
		return false
	# Hidden grants Reaction timing while facedown / played from facedown.
	return state == State.NEUTRAL_CLOSED or \
		state == State.SHOWDOWN_OPEN or \
		state == State.SHOWDOWN_CLOSED


static func can_activate_ability(ability: Dictionary, state: int, player_index: int, game_state: GameState) -> bool:
	var is_reaction = ability.get("is_reaction", false)
	var is_action = ability.get("is_action", false)
	if is_reaction:
		return (state == State.NEUTRAL_OPEN and player_index == game_state.turn_player_index) or \
			state == State.NEUTRAL_CLOSED or state == State.SHOWDOWN_OPEN or \
			state == State.SHOWDOWN_CLOSED
	if is_action:
		return state == State.NEUTRAL_OPEN or state == State.SHOWDOWN_OPEN
	# Standard activated abilities: only during NEUTRAL_OPEN on turn player's turn
	return state == State.NEUTRAL_OPEN and player_index == game_state.turn_player_index


static func next_phase(current: int) -> int:
	match current:
		Phase.AWAKEN: return Phase.BEGINNING
		Phase.BEGINNING: return Phase.CHANNEL
		Phase.CHANNEL: return Phase.DRAW
		Phase.DRAW: return Phase.MAIN
		Phase.MAIN: return Phase.ENDING
		Phase.ENDING: return Phase.AWAKEN
	return Phase.AWAKEN
