extends VBoxContainer
class_name RunHud

## In-run HUD displaying live run status (health, round, phase, run ID, opponent count).
##
## Bind to a RunController via bind_controller() after both nodes are ready.
## All label updates are driven by RunController signals; the HUD never polls state.

@onready var health_label: Label = %HealthLabel
@onready var round_label: Label = %RoundLabel
@onready var phase_label: Label = %PhaseLabel
@onready var run_id_label: Label = %RunIdLabel
@onready var opponent_label: Label = %OpponentLabel
@onready var planning_error_label: Label = %PlanningErrorLabel

var _controller: RunController

## Connects to all RunController signals and performs an immediate full refresh.
## Safely disconnects from any previously bound controller first.
func bind_controller(controller: RunController) -> void:
	if _controller != null and is_instance_valid(_controller):
		_disconnect_controller(_controller)
	_controller = controller
	_controller.phase_changed.connect(_on_phase_changed)
	_controller.run_health_changed.connect(_on_run_health_changed)
	_controller.run_ended.connect(_on_run_ended)
	_controller.round_advanced.connect(_on_round_advanced)
	_refresh_all()

func _exit_tree() -> void:
	if _controller != null and is_instance_valid(_controller):
		_disconnect_controller(_controller)

func _disconnect_controller(c: RunController) -> void:
	if c.phase_changed.is_connected(_on_phase_changed):
		c.phase_changed.disconnect(_on_phase_changed)
	if c.run_health_changed.is_connected(_on_run_health_changed):
		c.run_health_changed.disconnect(_on_run_health_changed)
	if c.run_ended.is_connected(_on_run_ended):
		c.run_ended.disconnect(_on_run_ended)
	if c.round_advanced.is_connected(_on_round_advanced):
		c.round_advanced.disconnect(_on_round_advanced)

func _refresh_all() -> void:
	if _controller == null or _controller.run_state == null:
		return
	var rs: RunState = _controller.run_state
	health_label.text = "Run health: %d / %d" % [rs.player_run_health, rs.params.starting_player_health]
	round_label.text = "Round: %d" % rs.current_round_index
	phase_label.text = "Phase: %s" % RoundPhase.phase_to_string(_controller.get_current_phase())
	run_id_label.text = "Run id: %s" % rs.run_id

## Updates the opponent champion count label. Called by RunShell on board_reset.
func update_opponent_label(count: int) -> void:
	opponent_label.text = "Opponent: %d champion%s" % [count, "s" if count != 1 else ""]

## Shows a planning error banner with the joined error strings. Automatically hidden
## by clear_planning_error() when the phase changes.
func show_planning_error(errors: PackedStringArray) -> void:
	planning_error_label.text = "Planning error: " + ", ".join(errors)
	planning_error_label.visible = true

## Hides and clears the planning error banner.
func clear_planning_error() -> void:
	planning_error_label.visible = false
	planning_error_label.text = ""

func _on_phase_changed(_p: RoundPhase.Phase) -> void:
	clear_planning_error()
	if _controller == null:
		return
	var rs: RunState = _controller.run_state
	if rs != null:
		health_label.text = "Run health: %d / %d" % [rs.player_run_health, rs.params.starting_player_health]
		round_label.text = "Round: %d" % rs.current_round_index
		run_id_label.text = "Run id: %s" % rs.run_id
	## After `run_ended`, `phase_changed` still fires; keep the end-game line instead of overwriting it.
	if rs == null or not rs.is_terminal:
		phase_label.text = "Phase: %s" % RoundPhase.phase_to_string(_controller.get_current_phase())

func _on_run_health_changed(new_health: int) -> void:
	if _controller != null and _controller.run_state != null:
		var rs: RunState = _controller.run_state
		health_label.text = "Run health: %d / %d" % [new_health, rs.params.starting_player_health]
		round_label.text = "Round: %d" % rs.current_round_index
		run_id_label.text = "Run id: %s" % rs.run_id

func _on_run_ended(player_survived: bool) -> void:
	phase_label.text = "Run ended (%s)" % ("victory" if player_survived else "defeat")

func _on_round_advanced(_new_round: int) -> void:
	if _controller != null and _controller.run_state != null:
		var rs: RunState = _controller.run_state
		round_label.text = "Round: %d" % rs.current_round_index
