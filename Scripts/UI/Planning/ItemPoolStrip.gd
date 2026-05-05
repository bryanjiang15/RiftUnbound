extends HBoxContainer
class_name ItemPoolStrip

## Shows assignable item cards from the deck. Pressing one assigns it to the board-view's selected champion.

@export var planning_controller: PlanningController
@export var planning_board_view: PlanningBoardView

## Tracks card instances available this round (rebuilt on board_reset).
var _available_cards: Array[CardInstance] = []

func _ready() -> void:
	if planning_controller != null:
		planning_controller.board_reset.connect(_rebuild)
		_rebuild()
	if planning_board_view != null:
		planning_board_view.champion_selected.connect(_on_champion_selected)
		planning_board_view.champion_removed.connect(_on_champion_removed)

func bind(controller: PlanningController, board_view: PlanningBoardView) -> void:
	if planning_controller != null and planning_controller.board_reset.is_connected(_rebuild):
		planning_controller.board_reset.disconnect(_rebuild)
	if planning_board_view != null:
		if planning_board_view.champion_selected.is_connected(_on_champion_selected):
			planning_board_view.champion_selected.disconnect(_on_champion_selected)
		if planning_board_view.champion_removed.is_connected(_on_champion_removed):
			planning_board_view.champion_removed.disconnect(_on_champion_removed)
	planning_controller = controller
	planning_board_view = board_view
	planning_controller.board_reset.connect(_rebuild)
	if planning_board_view != null:
		planning_board_view.champion_selected.connect(_on_champion_selected)
		planning_board_view.champion_removed.connect(_on_champion_removed)
	_rebuild()

func _rebuild() -> void:
	for child in get_children():
		child.queue_free()
	if planning_controller == null:
		return
	_available_cards = planning_controller.build_deck_card_instances()
	_refresh_buttons()

func _refresh_buttons() -> void:
	for child in get_children():
		child.queue_free()
	for inst in _available_cards:
		var btn := Button.new()
		btn.custom_minimum_size = Vector2(90, 60)
		var label := inst.definition.title if inst.definition != null and inst.definition.title != "" else "(item)"
		btn.text = label
		btn.tooltip_text = label
		btn.pressed.connect(_on_item_pressed.bind(inst))
		add_child(btn)

func _on_item_pressed(inst: CardInstance) -> void:
	if planning_controller == null or planning_board_view == null:
		return
	var sel_id: int = planning_board_view._selected_instance_id
	if sel_id < 0:
		push_warning("ItemPoolStrip: no champion selected on board")
		return
	var board: BoardState = planning_controller.board_state
	if board == null:
		return
	var params: PlanningParams = planning_controller.planning_params
	var ok := board.assign_item(sel_id, inst, params)
	if ok:
		_available_cards.erase(inst)
		_refresh_buttons()

func _on_champion_selected(_iid: int) -> void:
	_refresh_buttons()

func _on_champion_removed(_iid: int) -> void:
	# Return items to pool from removed champion.
	if planning_controller == null:
		return
	var board: BoardState = planning_controller.board_state
	if board == null:
		return
	# Champion is already removed, so we can't recover equipped cards from it.
	# Future: track returned items. For now rebuild from scratch (cheap for Phase C).
	_rebuild()
