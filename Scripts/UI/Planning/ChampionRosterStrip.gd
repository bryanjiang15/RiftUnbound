extends HBoxContainer
class_name ChampionRosterStrip

## Displays available champion buttons. Pressing one sets the "to-place" definition on PlanningBoardView.

@export var planning_board_view: PlanningBoardView
@export var planning_controller: PlanningController

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
	# Start with the hero; extras are stubs until economy unlocks them.
	var available: Array[ChampionData] = []
	if deck.hero != null:
		available.append(deck.hero)
	var params: PlanningParams = planning_controller.planning_params
	var max_slots: int = params.max_player_champions_on_board if params != null else 3
	# Stub extra slots
	while available.size() < max_slots:
		available.append(null)

	for i in range(available.size()):
		var def: ChampionData = available[i]
		var btn := Button.new()
		btn.custom_minimum_size = Vector2(90, 90)
		if def != null:
			btn.text = def.display_name
			btn.tooltip_text = def.display_name
			if def.portrait != null:
				btn.icon = def.portrait
			btn.pressed.connect(_on_champion_pressed.bind(def))
		else:
			btn.text = "— stub —"
			btn.disabled = true
		add_child(btn)

func _on_champion_pressed(def: ChampionData) -> void:
	if planning_board_view != null:
		planning_board_view.set_selected_champion_def(def)
