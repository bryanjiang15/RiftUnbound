extends Control
class_name CombatBoardView

## Step-by-step visual replay of a CombatResult event log.
##
## Called by RunShell when entering COMBAT_RESOLVE. Builds the same grid as
## PlanningBoardView, populates ChampionUI tokens from the snapshot, then
## plays each CombatEvent in order with a configurable delay between steps.
## Emits replay_finished when the COMBAT_END event is reached.

## Emitted after the last event (COMBAT_END) has been displayed.
signal replay_finished

## Pixels per grid cell (should match PlanningBoardView.cell_px in run_shell.tscn).
@export var cell_px: int = 90
## Optional cell background texture (same resource as PlanningBoardView).
@export var cell_texture: Texture2D
## Packed scene for unit tokens (champion_ui.tscn).
@export var champion_ui_scene: PackedScene
## Seconds between each event step.
@export var step_delay: float = 0.35

## Tint for player-side cells.
@export var color_player_cell: Color = Color(0.3713738, 0.7097166, 0.9536118, 1)
## Tint for opponent-side cells.
@export var color_opponent_cell: Color = Color(0.9373071, 0.33936462, 0.43448475, 1)

## key → BaseButton cell node
var _cell_buttons: Dictionary = {}
## combat instance_id → ChampionUI token node
var _unit_tokens: Dictionary = {}

var _spec: GridSpec = null
var _snapshot: PlanningSnapshot = null

## Builds the grid and starts playing back `result`.
## Safe to call multiple times; rebuilds everything from scratch each call.
func start_replay(
	result: CombatResult,
	snapshot: PlanningSnapshot,
	spec: GridSpec
) -> void:
	_spec = spec
	_snapshot = snapshot
	_build_grid(spec)
	_populate_tokens(snapshot)
	_run_replay(result)

# ── Grid construction (mirrors PlanningBoardView._build_grid) ────────────────

func _build_grid(spec: GridSpec) -> void:
	for child in get_children():
		child.queue_free()
	_cell_buttons.clear()
	_unit_tokens.clear()
	if spec == null:
		return
	custom_minimum_size = Vector2(spec.columns * cell_px, spec.total_rows() * cell_px)
	for coord in spec.iter_square_cells():
		var x := coord.square.x
		var y := coord.square.y
		var cell_size := Vector2(cell_px - 2, cell_px - 2)
		var cell_pos  := Vector2(x * cell_px, y * cell_px)
		var key := coord.to_key()
		var is_player := spec.is_player_deployable(coord)
		var base_color: Color = color_player_cell if is_player else color_opponent_cell
		if cell_texture != null:
			var tbtn := TextureButton.new()
			tbtn.position = cell_pos
			tbtn.size = cell_size
			tbtn.texture_normal = cell_texture
			tbtn.texture_hover  = cell_texture
			tbtn.texture_pressed = cell_texture
			tbtn.stretch_mode = TextureButton.STRETCH_SCALE
			tbtn.ignore_texture_size = true
			tbtn.modulate = base_color
			_cell_buttons[key] = tbtn
			add_child(tbtn)
		else:
			var btn := Button.new()
			btn.position = cell_pos
			btn.size = cell_size
			btn.flat = true
			btn.modulate = base_color
			btn.disabled = true
			_cell_buttons[key] = btn
			add_child(btn)

# ── Token placement ──────────────────────────────────────────────────────────

func _populate_tokens(snapshot: PlanningSnapshot) -> void:
	if champion_ui_scene == null:
		return
	for inst in snapshot.player_champions:
		_spawn_token(inst, true)
	for inst in snapshot.opponent_champions:
		_spawn_token(inst, false)

func _spawn_token(inst: ChampionInstance, _is_player: bool) -> void:
	if inst.cell == null:
		return
	var token: ChampionUI = champion_ui_scene.instantiate()
	token.definition = inst.definition
	token.instance_id = inst.instance_id
	token.position = _cell_center_pos(inst.cell)
	token.z_index = 1
	# Disable all interaction during replay.
	token.set_process_input(false)
	add_child(token)
	# Store by source instance_id so events can find the token.
	_unit_tokens[inst.instance_id] = token

## Returns the top-left position to place an 80×80 token centred in the cell.
func _cell_center_pos(coord: GridCoord) -> Vector2:
	var btn: BaseButton = _cell_buttons.get(coord.to_key(), null)
	if btn == null:
		return Vector2(coord.square.x * cell_px + (cell_px - 80) / 2.0,
					   coord.square.y * cell_px + (cell_px - 80) / 2.0)
	return btn.position + Vector2((cell_px - 80) / 2.0, (cell_px - 80) / 2.0)

# ── Replay coroutine ─────────────────────────────────────────────────────────

func _run_replay(result: CombatResult) -> void:
	for event: CombatEvent in result.events:
		_apply_event(event)
		if event.kind == CombatEvent.Kind.COMBAT_END:
			break
		await get_tree().create_timer(step_delay).timeout
	replay_finished.emit()

## Applies one CombatEvent to the visual state.
func _apply_event(event: CombatEvent) -> void:
	match event.kind:
		CombatEvent.Kind.MOVE:
			_on_event_move(event)
		CombatEvent.Kind.ATTACK:
			_on_event_attack(event)
		CombatEvent.Kind.DEATH:
			_on_event_death(event)
		CombatEvent.Kind.COMBAT_START, CombatEvent.Kind.COMBAT_END:
			pass

func _on_event_move(event: CombatEvent) -> void:
	# Find token by matching source_id: tokens are stored by ChampionInstance.instance_id,
	# which is the CombatUnit.source_id.
	var token: ChampionUI = _find_token_by_combat_id(event.actor_id)
	if token == null:
		return
	var dest := _cell_center_pos(event.actor_cell)
	get_tree().create_tween().tween_property(token, "position", dest, step_delay * 0.8)

func _on_event_attack(event: CombatEvent) -> void:
	var attacker: ChampionUI = _find_token_by_combat_id(event.actor_id)
	var defender: ChampionUI = _find_token_by_combat_id(event.target_id)
	if attacker != null:
		# Brief lunge toward target.
		var orig := attacker.position
		var toward: Vector2 = orig
		if defender != null:
			toward = orig + (defender.position - orig) * 0.25
		var tw := get_tree().create_tween()
		tw.tween_property(attacker, "position", toward, step_delay * 0.2)
		tw.tween_property(attacker, "position", orig,   step_delay * 0.2)
	if defender != null:
		# Flash red on hit.
		var tw2 := get_tree().create_tween()
		tw2.tween_property(defender, "modulate", Color(1, 0.2, 0.2), step_delay * 0.15)
		tw2.tween_property(defender, "modulate", Color.WHITE,          step_delay * 0.15)

func _on_event_death(event: CombatEvent) -> void:
	var token: ChampionUI = _find_token_by_combat_id(event.actor_id)
	if token == null:
		return
	var tw := get_tree().create_tween()
	tw.tween_property(token, "modulate:a", 0.0, step_delay * 0.5)
	tw.tween_callback(token.queue_free)

## Looks up a token using the combat unit's source_id (= ChampionInstance.instance_id).
## CombatBoard assigns combat instance_ids sequentially starting from 1, but
## _unit_tokens is keyed by the original ChampionInstance.instance_id (source_id).
## We iterate CombatBoard mapping via the snapshot occupancy to find the right token.
func _find_token_by_combat_id(combat_id: int) -> ChampionUI:
	# combat_id is the CombatUnit.instance_id assigned by CombatBoard.from_snapshot.
	# Player champions are processed first (id 1..N), then opponents (N+1..M).
	# Reconstruct the mapping by iterating the snapshot in the same order.
	if _snapshot == null:
		return null
	var idx := 0
	for inst in _snapshot.player_champions:
		idx += 1
		if idx == combat_id:
			return _unit_tokens.get(inst.instance_id, null)
	for inst in _snapshot.opponent_champions:
		idx += 1
		if idx == combat_id:
			return _unit_tokens.get(inst.instance_id, null)
	return null
