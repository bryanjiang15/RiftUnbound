extends HandUI
class_name HandStrip

## Planning-phase hand of cards, rendered using the existing HandUI/CardUI pipeline.
##
## Extends HandUI so cards fan out and hover exactly like the game hand. Overrides
## _select_card_hook to assign the chosen card to the selected champion on the board
## instead of emitting a PlayCardAction.
##
## Note: for drag-and-drop support, replace CardUI (Area2D) children with Control-based
## card widgets that implement _get_drag_data / _drop_data.

@export var planning_controller: PlanningController
@export var planning_board_view: PlanningBoardView

## Maps CardData → CardInstance so we can identify which instance was selected.
var _instance_map: Dictionary = {}

func _ready() -> void:
	super._ready()
	if planning_controller != null:
		planning_controller.board_reset.connect(_on_board_reset)
		_on_board_reset()
	if planning_board_view != null:
		planning_board_view.champion_removed.connect(_on_champion_removed)

## Binds the strip to a controller and board view at runtime (called by RunShell._ready).
func bind(controller: PlanningController, board_view: PlanningBoardView) -> void:
	if planning_controller != null and planning_controller.board_reset.is_connected(_on_board_reset):
		planning_controller.board_reset.disconnect(_on_board_reset)
	if planning_board_view != null and planning_board_view.champion_removed.is_connected(_on_champion_removed):
		planning_board_view.champion_removed.disconnect(_on_champion_removed)
	planning_controller = controller
	planning_board_view = board_view
	planning_controller.board_reset.connect(_on_board_reset)
	if planning_board_view != null:
		planning_board_view.champion_removed.connect(_on_champion_removed)
	_on_board_reset()

func _on_board_reset() -> void:
	_instance_map.clear()
	if planning_controller == null:
		return
	var instances: Array[CardInstance] = planning_controller.build_deck_card_instances()
	var defs: Array[CardData] = []
	for inst in instances:
		if inst.definition != null:
			defs.append(inst.definition)
			_instance_map[inst.definition] = inst
	populate_from_card_list(defs)

## Called by CardContainer when a card is clicked (state and index are null/-1 here).
func _select_card_hook(card: CardData, _state: GameState, _index: int) -> void:
	if planning_controller == null or planning_board_view == null:
		return
	var sel_id: int = planning_board_view._selected_instance_id
	if sel_id < 0:
		push_warning("HandStrip: no champion selected on board")
		return
	var inst: CardInstance = _instance_map.get(card, null)
	if inst == null:
		return
	var board: BoardState = planning_controller.board_state
	if board == null:
		return
	if board.assign_item(sel_id, inst, planning_controller.planning_params):
		_instance_map.erase(card)
		for child in get_children():
			if child is CardUI and child.referenced_card == card:
				child.queue_free()
				break
		set_locations()

func _on_champion_removed(_iid: int) -> void:
	# Rebuild the full hand when a champion (and its items) is removed from the board.
	_on_board_reset()
