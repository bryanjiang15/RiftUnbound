extends Control
class_name PlanningBoardView

## C3 grid UI.
##
## Interaction model:
##   Roster drag  → drag ChampionUI from roster, drop on player cell to place.
##   Board drag   → drag a placed token to another player cell to move it.
##   Right-click token → remove champion.
##   Click cell (no drag) → legacy click-to-select-then-click-to-place flow still works.
##
## Champion tokens are ChampionUI (Area2D) nodes layered on top of cell buttons.
## A translucent ghost follows the cursor during drag.

signal champion_placed(instance_id: int)
signal champion_removed(instance_id: int)
signal champion_selected(instance_id: int)

## Pixels per grid cell square.
@export var cell_px: int = 100
## Optional cell background texture. Uses a colored Button when null.
@export var cell_texture: Texture2D
## PackedScene for champion tokens and drag ghost (champion_ui.tscn).
@export var champion_ui_scene: PackedScene

@export var planning_controller: PlanningController

@export var color_player_cell: Color = Color(0.12, 0.18, 0.25)
@export var color_opponent_cell: Color = Color(0.2, 0.1, 0.1)
@export var color_selected: Color = Color(0.9, 0.8, 0.2, 0.5)

var _selected_champion_def: ChampionData = null
var _selected_instance_id: int = -1

## key → BaseButton
var _cell_buttons: Dictionary = {}
## key → GridCoord (reverse map, populated in _build_grid)
var _key_to_coord: Dictionary = {}
## instance_id → ChampionUI token node
var _board_tokens: Dictionary = {}

# ── drag state ──────────────────────────────────────────────────────────────
## True while a drag is in progress.
var _dragging: bool = false
## Champion def being dragged (from roster). null when dragging a board token.
var _drag_def: ChampionData = null
## instance_id of the board token being dragged. -1 when dragging from roster.
var _drag_source_iid: int = -1
## The ghost ChampionUI that follows the cursor.
var _drag_ghost: ChampionUI = null
## Source widget (roster or board token) dimmed during drag.
var _drag_source_ui: ChampionUI = null

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

## Legacy API: select a champion def so the next board-cell click places it.
func set_selected_champion_def(def: ChampionData) -> void:
	_selected_champion_def = def
	_selected_instance_id = -1
	_refresh_tokens()

## Called by ChampionRosterStrip when the player begins dragging a roster widget.
## source_ui is the roster ChampionUI that fired drag_started.
func begin_roster_drag(def: ChampionData, source_ui: ChampionUI) -> void:
	if _dragging:
		return
	_dragging = true
	_drag_def = def
	_drag_source_iid = -1
	_drag_source_ui = source_ui
	_spawn_ghost(def, source_ui.global_position)
	set_process_input(true)

# ── grid construction ────────────────────────────────────────────────────────

func _build_grid() -> void:
	for child in get_children():
		child.queue_free()
	_cell_buttons.clear()
	_key_to_coord.clear()
	_board_tokens.clear()
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
		_key_to_coord[key] = coord
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

# ── token management ─────────────────────────────────────────────────────────

func _on_board_reset() -> void:
	_selected_instance_id = -1
	_cancel_drag()
	# Tokens will be rebuilt by _refresh_tokens.
	_refresh_tokens()

func _refresh_tokens() -> void:
	if planning_controller == null:
		return
	var spec: GridSpec = planning_controller.grid_spec
	var board: BoardState = planning_controller.board_state
	if spec == null:
		return

	# ── cell colours ──────────────────────────────────────────────────────
	for coord in spec.iter_square_cells():
		var key := coord.to_key()
		var cell_node: BaseButton = _cell_buttons.get(key, null)
		if cell_node == null:
			continue
		var is_player_side := spec.is_player_deployable(coord)
		var base_color: Color = color_player_cell if is_player_side else color_opponent_cell
		var occ_entry: Variant = board.occupancy.get(key, null) if board != null else null
		var is_selected := (
			occ_entry is Dictionary
			and int(occ_entry.get("instance_id", -1)) == _selected_instance_id
			and _selected_instance_id >= 0
		)
		cell_node.modulate = base_color.lerp(Color(0.9, 0.8, 0.2), 0.6 if is_selected else 0.0)
		# Clear legacy text labels on cells — tokens show names now.
		if cell_node is Button:
			(cell_node as Button).text = ""
		else:
			_set_texture_button_label(cell_node, "")

	if board == null:
		return

	# ── remove stale tokens ───────────────────────────────────────────────
	var live_iids: Array = board.player_champions.map(func(c: ChampionInstance) -> int: return c.instance_id)
	for iid in _board_tokens.keys():
		if iid not in live_iids:
			if is_instance_valid(_board_tokens[iid]):
				_board_tokens[iid].queue_free()
			_board_tokens.erase(iid)

	# ── add / reposition tokens ───────────────────────────────────────────
	for champ in board.player_champions:
		var iid: int = champ.instance_id
		var coord: GridCoord = _find_champion_coord(champ, board)
		if coord == null:
			continue
		var cell_node: BaseButton = _cell_buttons.get(coord.to_key(), null)
		if cell_node == null:
			continue
		# Offset so the 80×80 token is centred in the cell.
		var token_pos: Vector2 = cell_node.position + Vector2((cell_px - 80) / 2.0, (cell_px - 80) / 2.0)
		if iid not in _board_tokens:
			if champion_ui_scene == null:
				continue
			var token: ChampionUI = champion_ui_scene.instantiate()
			token.definition = champ.definition
			token.instance_id = iid
			token.position = token_pos
			token.z_index = 1
			add_child(token)
			token.drag_started.connect(func(ui: ChampionUI): _start_board_drag(ui, ui.instance_id))
			token.right_clicked.connect(func(ui: ChampionUI): _on_token_right_clicked(ui.instance_id))
			_board_tokens[iid] = token
		else:
			_board_tokens[iid].position = token_pos

## Returns the GridCoord where champ currently sits, using occupancy.
func _find_champion_coord(champ: ChampionInstance, board: BoardState) -> GridCoord:
	for key in board.occupancy:
		var entry: Variant = board.occupancy[key]
		if entry is Dictionary and int(entry.get("instance_id", -1)) == champ.instance_id:
			return _key_to_coord.get(key, null)
	return null

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

# ── drag helpers ─────────────────────────────────────────────────────────────

## Begins dragging an already-placed board token.
func _start_board_drag(source_ui: ChampionUI, iid: int) -> void:
	if _dragging:
		return
	var board: BoardState = planning_controller.board_state if planning_controller != null else null
	if board == null:
		return
	var champ: ChampionInstance = board.find_champion(iid)
	if champ == null:
		return
	_dragging = true
	_drag_def = null
	_drag_source_iid = iid
	_drag_source_ui = source_ui
	source_ui.modulate.a = 0.3
	_spawn_ghost(champ.definition, source_ui.global_position)
	set_process_input(true)

## Creates the ghost widget that follows the cursor during a drag.
func _spawn_ghost(def: ChampionData, start_pos: Vector2) -> void:
	if champion_ui_scene == null:
		return
	_drag_ghost = champion_ui_scene.instantiate()
	_drag_ghost.definition = def
	_drag_ghost.modulate.a = 0.65
	_drag_ghost.z_index = 100
	add_child(_drag_ghost)
	_drag_ghost.global_position = start_pos

func _input(event: InputEvent) -> void:
	if not _dragging:
		return
	if event is InputEventMouseMotion:
		if _drag_ghost != null:
			# Centre the ghost on the cursor.
			_drag_ghost.global_position = get_global_mouse_position() - Vector2(40, 40)
	elif event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT and not mb.pressed:
			_finish_drag()

## Resolves the drop when LMB is released.
func _finish_drag() -> void:
	if planning_controller == null:
		_cancel_drag()
		return
	var board: BoardState = planning_controller.board_state
	var spec: GridSpec = planning_controller.grid_spec
	if board == null or spec == null:
		_cancel_drag()
		return

	var coord: GridCoord = _get_cell_at_global_pos(get_global_mouse_position())
	var placed := false

	if coord != null and spec.is_player_deployable(coord):
		var key := coord.to_key()
		var occ_entry: Variant = board.occupancy.get(key, null)
		if _drag_source_iid < 0 and _drag_def != null:
			# Roster → board: place champion.
			if not (occ_entry is Dictionary):
				var ok := board.place_player_champion(
					_drag_def, coord,
					planning_controller.run_controller.scope,
					planning_controller.planning_params
				)
				if ok:
					var placed_iid: int = board.player_champions.back().instance_id
					champion_placed.emit(placed_iid)
					placed = true
		elif _drag_source_iid >= 0:
			# Board → board: move token.
			var current_key := _key_for_iid(_drag_source_iid, board)
			if current_key != key:
				board.move_player_champion(
					_drag_source_iid, coord,
					planning_controller.run_controller.scope
				)
			placed = true

	if not placed and _drag_source_iid < 0 and _drag_def != null:
		# Dropped outside the board → fall back to click-to-place selection.
		set_selected_champion_def(_drag_def)

	_cancel_drag()
	_refresh_tokens()

## Cancels the drag and restores all visual state.
func _cancel_drag() -> void:
	set_process_input(false)
	_dragging = false
	_drag_def = null
	_drag_source_iid = -1
	if _drag_ghost != null and is_instance_valid(_drag_ghost):
		_drag_ghost.queue_free()
	_drag_ghost = null
	if _drag_source_ui != null and is_instance_valid(_drag_source_ui):
		_drag_source_ui.modulate.a = 1.0
	_drag_source_ui = null

## Returns the GridCoord of the cell under global_pos, or null if none.
func _get_cell_at_global_pos(global_pos: Vector2) -> GridCoord:
	for key in _cell_buttons:
		var btn: BaseButton = _cell_buttons[key]
		var rect := Rect2(btn.global_position, btn.size)
		if rect.has_point(global_pos):
			return _key_to_coord.get(key, null)
	return null

## Returns the occupancy key for the cell holding iid.
func _key_for_iid(iid: int, board: BoardState) -> String:
	for key in board.occupancy:
		var entry: Variant = board.occupancy[key]
		if entry is Dictionary and int(entry.get("instance_id", -1)) == iid:
			return key
	return ""

# ── cell click handlers (legacy click-to-select-then-click flow) ─────────────

func _on_cell_left_click(coord: GridCoord) -> void:
	if _dragging:
		return
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
		var iid: int = int(occ_entry.get("instance_id", -1))
		_selected_instance_id = iid
		_selected_champion_def = null
		champion_selected.emit(iid)
		_refresh_tokens()
	elif _selected_instance_id >= 0:
		board.move_player_champion(_selected_instance_id, coord, planning_controller.run_controller.scope)
		_selected_instance_id = -1
		_refresh_tokens()
	elif _selected_champion_def != null:
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
	if _dragging:
		return
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
			if board.player_champions.any(func(c: ChampionInstance) -> bool: return c.instance_id == iid):
				board.remove_player_champion(iid)
				if _selected_instance_id == iid:
					_selected_instance_id = -1
				champion_removed.emit(iid)
				_refresh_tokens()

func _on_token_right_clicked(iid: int) -> void:
	if planning_controller == null:
		return
	var board: BoardState = planning_controller.board_state
	if board == null:
		return
	if board.player_champions.any(func(c: ChampionInstance) -> bool: return c.instance_id == iid):
		board.remove_player_champion(iid)
		if _selected_instance_id == iid:
			_selected_instance_id = -1
		champion_removed.emit(iid)
		_refresh_tokens()
