extends Control
class_name PlanningBoardView

## C3 grid UI. Click empty player cell (with champ selected) → place.
## Click occupied player cell → select instance. Click another empty cell → move.
## Alt-click (right-click) occupied player cell → remove.

signal champion_placed(instance_id: int)
signal champion_removed(instance_id: int)
signal champion_selected(instance_id: int)

## Pixels per cell square.
@export var cell_px: int = 100
## Optional cell background texture (e.g. Assets/grids.png). Uses colored Button when null.
@export var cell_texture: Texture2D

@export var planning_controller: PlanningController

## Player half cell tint (normal).
@export var color_player_cell: Color = Color(0.12, 0.18, 0.25)
## Opponent half cell tint.
@export var color_opponent_cell: Color = Color(0.2, 0.1, 0.1)
## Highlight for the currently selected player champion cell.
@export var color_selected: Color = Color(0.9, 0.8, 0.2, 0.5)

var _selected_champion_def: ChampionData = null
var _selected_instance_id: int = -1

## Map GridCoord.to_key() -> BaseButton node
var _cell_buttons: Dictionary = {}

func _ready() -> void:
	if planning_controller != null:
		planning_controller.board_reset.connect(_on_board_reset)
		_build_grid()
		_refresh_tokens()

func bind_controller(controller: PlanningController) -> void:
	if planning_controller != null and planning_controller.board_reset.is_connected(_on_board_reset):
		planning_controller.board_reset.disconnect(_on_board_reset)
	planning_controller = controller
	planning_controller.board_reset.connect(_on_board_reset)
	_build_grid()
	_refresh_tokens()

func set_selected_champion_def(def: ChampionData) -> void:
	_selected_champion_def = def
	_selected_instance_id = -1
	_refresh_tokens()

func _build_grid() -> void:
	for child in get_children():
		child.queue_free()
	_cell_buttons.clear()
	if planning_controller == null:
		return
	var spec: GridSpec = planning_controller.grid_spec
	if spec == null:
		return
	custom_minimum_size = Vector2(spec.columns * cell_px, spec.total_rows() * cell_px)
	for coord in spec.iter_square_cells():
		var x := coord.square.x
		var y := coord.square.y
		var cell_size := Vector2(cell_px - 2, cell_px - 2)
		var cell_pos := Vector2(x * cell_px, y * cell_px)
		var key := coord.to_key()
		if cell_texture != null:
			var tbtn := TextureButton.new()
			tbtn.position = cell_pos
			tbtn.size = cell_size
			tbtn.texture_normal = cell_texture
			tbtn.texture_hover = cell_texture
			tbtn.texture_pressed = cell_texture
			tbtn.stretch_mode = TextureButton.STRETCH_SCALE
			tbtn.ignore_texture_size = true
			_cell_buttons[key] = tbtn
			add_child(tbtn)
			tbtn.pressed.connect(_on_cell_left_click.bind(coord))
			tbtn.gui_input.connect(_on_cell_gui_input.bind(coord))
		else:
			var btn := Button.new()
			btn.position = cell_pos
			btn.size = cell_size
			btn.flat = true
			_cell_buttons[key] = btn
			add_child(btn)
			btn.pressed.connect(_on_cell_left_click.bind(coord))
			btn.gui_input.connect(_on_cell_gui_input.bind(coord))

func _on_board_reset() -> void:
	_selected_instance_id = -1
	_refresh_tokens()

func _refresh_tokens() -> void:
	if planning_controller == null:
		return
	var spec: GridSpec = planning_controller.grid_spec
	var board: BoardState = planning_controller.board_state
	if spec == null:
		return
	for coord in spec.iter_square_cells():
		var key := coord.to_key()
		var cell_node: BaseButton = _cell_buttons.get(key, null)
		if cell_node == null:
			continue
		var is_player_side := spec.is_player_deployable(coord)
		var base_color: Color = color_player_cell if is_player_side else color_opponent_cell
		var occ_entry: Variant = board.occupancy.get(key, null) if board != null else null
		var label_text: String = ""
		if occ_entry is Dictionary:
			var iid: int = int(occ_entry.get("instance_id", -1))
			var champ := board.find_champion(iid) if board != null else null
			if champ != null:
				label_text = champ.definition.display_name if champ.definition != null else "?"
		var is_selected := (
			occ_entry is Dictionary
			and int(occ_entry.get("instance_id", -1)) == _selected_instance_id
			and _selected_instance_id >= 0
		)
		var final_color := base_color.lerp(Color(0.9, 0.8, 0.2), 0.6 if is_selected else 0.0)
		cell_node.modulate = final_color
		# Text label: Button has .text; TextureButton gets a child Label.
		if cell_node is Button:
			(cell_node as Button).text = label_text
		else:
			_set_texture_button_label(cell_node, label_text)

func _set_texture_button_label(node: BaseButton, text: String) -> void:
	var lbl: Label = null
	for ch in node.get_children():
		if ch is Label:
			lbl = ch as Label
			break
	if lbl == null:
		lbl = Label.new()
		lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		lbl.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		lbl.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		lbl.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		lbl.mouse_filter = Control.MOUSE_FILTER_IGNORE
		node.add_child(lbl)
	lbl.text = text

func _on_cell_left_click(coord: GridCoord) -> void:
	if planning_controller == null:
		return
	var board: BoardState = planning_controller.board_state
	var spec: GridSpec = planning_controller.grid_spec
	if board == null or spec == null:
		return
	if not spec.is_player_deployable(coord):
		return
	var key := coord.to_key()
	var occ_entry: Variant = board.occupancy.get(key, null)
	if occ_entry is Dictionary:
		# Select this champion instance
		var iid: int = int(occ_entry.get("instance_id", -1))
		_selected_instance_id = iid
		_selected_champion_def = null
		champion_selected.emit(iid)
		_refresh_tokens()
	elif _selected_instance_id >= 0:
		# Move selected instance to this empty cell
		board.move_player_champion(_selected_instance_id, coord, planning_controller.run_controller.scope)
		_selected_instance_id = -1
		_refresh_tokens()
	elif _selected_champion_def != null:
		# Place new champion here
		var ok := board.place_player_champion(
			_selected_champion_def, coord,
			planning_controller.run_controller.scope,
			planning_controller.planning_params
		)
		if ok:
			var placed_iid: int = board.player_champions.back().instance_id
			_selected_champion_def = null
			champion_placed.emit(placed_iid)
		_refresh_tokens()

func _on_cell_gui_input(event: InputEvent, coord: GridCoord) -> void:
	if planning_controller == null:
		return
	if event.is_action_released("Alt Select"):
		var board: BoardState = planning_controller.board_state
		if board == null:
			return
		var key := coord.to_key()
		var occ_entry: Variant = board.occupancy.get(key, null)
		if occ_entry is Dictionary:
			var iid: int = int(occ_entry.get("instance_id", -1))
			if board.player_champions.any(func(c): return c.instance_id == iid):
				board.remove_player_champion(iid)
				if _selected_instance_id == iid:
					_selected_instance_id = -1
				champion_removed.emit(iid)
				_refresh_tokens()
