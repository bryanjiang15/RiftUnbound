extends HBoxContainer
class_name ChampionRosterStrip

## Displays available champions as interactive ChampionUI Area2D widgets.
##
## Pressing (or dragging) a roster widget either:
##   - Starts a drag: board view creates a ghost and places on drop.
##   - Quick-releases outside the board: board view falls back to click-to-place
##     by setting the selected champion def on PlanningBoardView.

@export var planning_board_view: PlanningBoardView
@export var planning_controller: PlanningController
## Packed scene for instantiating ChampionUI widgets (champion_ui.tscn).
@export var champion_ui_scene: PackedScene

func _ready() -> void:
	if planning_controller != null:
		planning_controller.board_reset.connect(_rebuild)
		_rebuild()

func bind(controller: PlanningController, board_view: PlanningBoardView) -> void:
	if planning_controller != null and planning_controller.board_reset.is_connected(_rebuild):
		planning_controller.board_reset.disconnect(_rebuild)
	planning_controller = controller
	planning_board_view = board_view
	planning_controller.board_reset.connect(_rebuild)
	_rebuild()

func _rebuild() -> void:
	for child in get_children():
		child.queue_free()
	if planning_controller == null:
		return
	var deck: Deck = planning_controller.player_deck
	if deck == null:
		return
	var available: Array[ChampionData] = []
	if deck.hero != null:
		available.append(deck.hero)
	var params: PlanningParams = planning_controller.planning_params
	var max_slots: int = params.max_player_champions_on_board if params != null else 3
	while available.size() < max_slots:
		available.append(null)

	for i in range(available.size()):
		var def: ChampionData = available[i]
		if def != null and champion_ui_scene != null:
			# Wrap in a Control so HBoxContainer can lay it out correctly.
			# Area2D (Node2D) nodes are invisible to flow-layout containers.
			var slot := Control.new()
			slot.custom_minimum_size = Vector2(80, 80)
			add_child(slot)
			var ui: ChampionUI = champion_ui_scene.instantiate()
			ui.definition = def
			slot.add_child(ui)
			ui.drag_started.connect(_on_champion_drag_started)
		else:
			var stub := Button.new()
			stub.custom_minimum_size = Vector2(80, 80)
			stub.text = def.display_name if def != null else "— stub —"
			stub.disabled = def == null
			if def != null:
				if def.portrait != null:
					stub.icon = def.portrait
				stub.pressed.connect(func(): _fallback_select(def))
			add_child(stub)

func _on_champion_drag_started(ui: ChampionUI) -> void:
	if planning_board_view != null:
		planning_board_view.begin_roster_drag(ui.definition, ui)

func _fallback_select(def: ChampionData) -> void:
	if planning_board_view != null:
		planning_board_view.set_selected_champion_def(def)
