extends Node
class_name PlanningController

## Owns BoardState for the current planning segment and syncs with RunController lifecycle.

signal board_reset

@export var run_controller: RunController
@export var grid_spec: GridSpec
@export var planning_params: PlanningParams
@export var opponent_stub: OpponentPlanningStub
@export var player_deck: Deck
## If true, places `player_deck.hero` on square (1, 7) when the run starts / round advances (dev stub until UI).
@export var auto_place_deck_hero: bool = true

var board_state: BoardState

func _ready() -> void:
	if planning_params == null:
		planning_params = PlanningParams.new()
	if grid_spec == null:
		grid_spec = GridSpec.default_square_5x3_two_sided()
	if opponent_stub == null:
		opponent_stub = OpponentPlanningStub.new()
	call_deferred("_try_connect_run")

func _try_connect_run() -> void:
	if run_controller == null:
		return
	if not run_controller.run_started.is_connected(_on_run_started):
		run_controller.run_started.connect(_on_run_started)
	if not run_controller.round_advanced.is_connected(_on_round_advanced):
		run_controller.round_advanced.connect(_on_round_advanced)
	_on_run_started()

func _on_run_started() -> void:
	reset_board()

func _on_round_advanced(_idx: int) -> void:
	reset_board()

func reset_board() -> void:
	if grid_spec == null:
		grid_spec = GridSpec.default_square_5x3_two_sided()
	board_state = BoardState.new(grid_spec)
	if run_controller == null or run_controller.scope == null:
		return
	opponent_stub.apply_to(board_state, run_controller.scope)
	if auto_place_deck_hero and player_deck != null and player_deck.hero != null:
		var hero_cell := GridCoord.from_square(Vector2i(1, 7))
		board_state.place_player_champion(player_deck.hero, hero_cell, run_controller.scope, planning_params)
	board_state.rebuild_occupancy()
	board_reset.emit()

func get_board_state() -> BoardState:
	return board_state

func validate_planning() -> PackedStringArray:
	if board_state == null:
		return PackedStringArray(["Board state missing."])
	return PlanningValidator.validate(board_state, planning_params)

## Card instances for the deck `main` pool (Phase C item UI).
func build_deck_card_instances() -> Array[CardInstance]:
	if run_controller == null or player_deck == null:
		return []
	return DeckInstanceBuilder.build_main_deck_cards(player_deck, run_controller.scope)
